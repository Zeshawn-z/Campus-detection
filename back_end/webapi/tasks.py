import logging
import random
from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from .models import (
    Area,
    CO2Data,
    HistoricalData,
    ProcessTerminal,
    TemperatureHumidityData,
)
from celery import shared_task

logger = logging.getLogger('django')


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _jitter(base, ratio=0.08):
    if base is None:
        return None
    amplitude = max(abs(base) * ratio, 1)
    return base + random.uniform(-amplitude, amplitude)


def _get_monthly_factor(month):
    monthly_factors = {
        1: 0.2,
        2: 0.1,
        3: 0.9,
        4: 1.0,
        5: 1.0,
        6: 1.3,
        7: 0.4,
        8: 0.3,
        9: 1.2,
        10: 1.5,
        11: 1.6,
        12: 1.4,
    }
    return monthly_factors.get(month, 1.0)


def _get_seasonal_temperature_factor(month):
    if month in [11, 12, 1, 2, 3]:
        return -5
    if month in [6, 7, 8]:
        return 5
    if month in [4, 5]:
        return 2
    return -1


def _get_seasonal_humidity_factor(month):
    if month in [6, 7, 8]:
        return 10
    if month in [11, 12, 1, 2, 3]:
        return -10
    return 0


def _get_hourly_people_factor(hour):
    if 8 <= hour <= 9:
        return 1.2
    if 10 <= hour <= 11:
        return 1.1
    if 12 <= hour <= 13:
        return 0.3
    if 14 <= hour <= 16:
        return 1.0
    if 17 <= hour <= 18:
        return 0.3
    if 19 <= hour <= 21:
        return 1.3
    if 22 <= hour <= 23:
        return 0.6
    return 0.1


def _get_hourly_temperature_factor(hour):
    if 10 <= hour <= 16:
        return 2
    if hour >= 22 or hour <= 6:
        return -1
    return 0


def _get_weekend_factor(is_weekend):
    return 0.6 if is_weekend else 1.0


def _get_holiday_factor(local_date):
    month_day = (local_date.month, local_date.day)
    holidays = {
        (1, 1): 0.3,
        (5, 1): 0.4,
        (10, 1): 0.3,
        (10, 2): 0.4,
        (10, 3): 0.5,
        (10, 4): 0.6,
        (10, 5): 0.7,
        (10, 6): 0.8,
        (10, 7): 0.9,
    }
    return holidays.get(month_day, 1.0)


def _get_exam_factor(local_date):
    month = local_date.month
    day = local_date.day
    if month == 6 and 10 <= day <= 30:
        return 1.2
    if month == 12 and 15 <= day <= 31:
        return 1.3
    return 1.0


def _get_area_type_factor(area_name):
    name = (area_name or '').lower()
    if any(keyword in name for keyword in ['食堂', '餐厅', 'cafe', '咖啡']):
        return 'dining', 2.0
    if any(keyword in name for keyword in ['正心', '致知', 'lecture']):
        return 'classroom', 1.5
    if any(keyword in name for keyword in ['图书馆']):
        return 'study', 1.8
    if any(keyword in name for keyword in ['宿舍', 'dorm']):
        return 'dorm', 0.8
    if any(keyword in name for keyword in ['实验室', 'lab']):
        return 'lab', 1.2
    return 'other', 1.0


def _get_area_time_factor(area_type, hour, is_weekend):
    if area_type == 'dining':
        if (11 <= hour <= 13) or (17 <= hour <= 19):
            return 2.5
        return 0.4
    if area_type == 'classroom':
        if (8 <= hour <= 12) or (14 <= hour <= 18):
            return 1.8 if not is_weekend else 0.3
        return 0.5
    if area_type == 'study':
        if 8 <= hour <= 22:
            return 2.0
        return 0.2
    if area_type == 'dorm':
        if (20 <= hour <= 24) or (0 <= hour <= 8):
            return 1.5 if is_weekend else 1.2
        return 0.7
    if area_type == 'lab':
        if (9 <= hour <= 18) and not is_weekend:
            return 1.5
        return 0.3
    return 1.0

@shared_task
def check_terminal_connections():
    """
    定期检查所有终端的连接状态，
    如果终端长时间未活动，则标记为离线
    """
    try:
        # 设置超时时间（3分钟）
        timeout = timezone.now() - timedelta(minutes=3)
        
        # 查找所有标记为在线但长时间未活动的终端
        inactive_terminals = ProcessTerminal.objects.filter(
            status=True,  # 当前标记为在线
            last_active__lt=timeout  # 但最后活动时间超过3分钟
        )
        
        # 更新这些终端的状态为离线
        count = 0
        for terminal in inactive_terminals:
            # 检查缓存中是否有连接状态
            cache_key = f"terminal:{terminal.id}:connected"
            is_connected = cache.get(cache_key)
            
            # 如果缓存明确指示为未连接，或者缓存中没有该值（判断为未连接）
            if is_connected is False or is_connected is None:
                terminal.status = False
                terminal.save(update_fields=['status'])
                
                # 更新状态缓存
                status_cache_key = f"terminal:{terminal.id}:status"
                cached_status = cache.get(status_cache_key)
                if cached_status:
                    cached_status.update({"terminal_online": False})
                    cache.set(status_cache_key, cached_status, timeout=60)
                
                count += 1
                logger.info(f"终端 {terminal.id} 已自动标记为离线 (长时间未活动)")
        
        if count > 0:
            logger.info(f"共有 {count} 个终端被自动标记为离线")
        
        return count
    except Exception as e:
        logger.error(f"检查终端连接状态时出错: {str(e)}")
        return 0


@shared_task
def generate_realtime_data_snapshot():
    """
    每次执行写入一批实时快照数据：
    - HistoricalData（人数）
    - TemperatureHumidityData（温湿度）
    - CO2Data（CO2/TVOC）
    """
    try:
        now = timezone.now()
        local_now = timezone.localtime(now)
        local_date = local_now.date()
        hour = local_now.hour
        is_weekend = local_now.weekday() >= 5

        monthly_factor = _get_monthly_factor(local_date.month)
        hourly_factor = _get_hourly_people_factor(hour)
        weekend_factor = _get_weekend_factor(is_weekend)
        holiday_factor = _get_holiday_factor(local_date)
        exam_factor = _get_exam_factor(local_date)

        seasonal_temp = _get_seasonal_temperature_factor(local_date.month)
        seasonal_humid = _get_seasonal_humidity_factor(local_date.month)
        hourly_temp = _get_hourly_temperature_factor(hour)

        area_count = 0
        co2_count = 0

        areas = Area.objects.select_related('bound_node', 'bound_node__terminal').all()
        for area in areas:
            node = area.bound_node
            if not node:
                continue

            area_type, base_factor = _get_area_type_factor(area.name)
            area_time_factor = _get_area_time_factor(area_type, hour, is_weekend)

            base_count = (20 + random.randint(0, 30)) * base_factor
            final_count = base_count * monthly_factor * hourly_factor * weekend_factor
            final_count *= holiday_factor * exam_factor * area_time_factor
            area_specific_factor = (area.id % 5 + 1) * 0.3
            random_factor = 0.8 + random.random() * 0.4
            detected_count = int(
                _clamp(
                    round(final_count * random_factor * area_specific_factor),
                    0,
                    600,
                )
            )

            base_temp = 22 + seasonal_temp + hourly_temp
            area_temp_adjust = (area.id % 3 - 1) * 0.5
            temperature = round(
                _clamp(base_temp + area_temp_adjust + (random.random() - 0.5) * 2, -10, 50),
                1,
            )
            base_humidity = 60 + seasonal_humid - (temperature - 22) * 1.5
            humidity = round(
                _clamp(base_humidity + (random.random() - 0.5) * 10, 25, 90),
                1,
            )

            if random.random() < 0.02:
                if random.random() < 0.5:
                    temperature = round(_clamp(temperature + random.choice([-5, -3, 3, 5]), -10, 50), 1)
                    humidity = float(random.choice([20, 25, 85, 90]))
                else:
                    temperature = round(_clamp(temperature + 2, -10, 50), 1)
                    humidity = round(_clamp(humidity + 15, 25, 95), 1)

            HistoricalData.objects.create(
                area=area,
                detected_count=detected_count,
                timestamp=now,
            )
            TemperatureHumidityData.objects.create(
                area=area,
                temperature=temperature,
                humidity=humidity,
                timestamp=now,
            )

            node.detected_count = detected_count
            node.temperature = temperature
            node.humidity = humidity
            node.status = True
            node.save(update_fields=['detected_count', 'temperature', 'humidity', 'status', 'updated_at'])

            area_count += 1

        terminals = ProcessTerminal.objects.all()
        for terminal in terminals:
            people_density = monthly_factor * hourly_factor * weekend_factor
            co2_base = 400 + (people_density * 300)
            co2_level = int(_clamp(co2_base + (random.random() - 0.5) * 100, 350, 2000))

            base_tvoc = 0.3 + (people_density * 0.5)
            seasonal_tvoc_factor = 1.2 if local_date.month in [6, 7, 8] else 1.0
            tvoc_level = round(
                _clamp(
                    base_tvoc * seasonal_tvoc_factor + (random.random() - 0.5) * 0.3,
                    0.1,
                    3.0,
                ),
                2,
            )

            if (8 <= hour <= 18) and not is_weekend:
                co2_level = int(co2_level * 0.8)
                tvoc_level = round(tvoc_level * 0.7, 2)

            if random.random() < 0.008:
                if random.random() < 0.6:
                    co2_level = 1800 + random.randint(0, 500)
                    tvoc_level = round(2.5 + random.random() * 1.0, 2)
                else:
                    co2_level = 300 + random.randint(0, 50)
                    tvoc_level = round(0.1 + random.random() * 0.1, 2)

            co2_level = int(_clamp(co2_level, 300, 2300))
            tvoc_level = round(_clamp(tvoc_level, 0.1, 3.5), 2)

            CO2Data.objects.create(
                terminal=terminal,
                co2_level=co2_level,
                tvoc_level=tvoc_level,
                timestamp=now,
            )

            terminal.co2_level = co2_level
            terminal.save(update_fields=['co2_level'])
            co2_count += 1

        logger.info(
            "实时数据快照生成完成: 区域=%s 条(人数+温湿度), 终端=%s 条(CO2/TVOC), 时间=%s",
            area_count,
            co2_count,
            now.isoformat(),
        )
        return {
            'area_records': area_count,
            'co2_records': co2_count,
            'timestamp': now.isoformat(),
        }
    except Exception as e:
        logger.exception("生成实时快照数据时出错: %s", str(e))
        return {'error': str(e)}
