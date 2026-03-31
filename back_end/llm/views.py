from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.views import View
from rest_framework.permissions import IsAuthenticated
from django.http import StreamingHttpResponse
from django.utils import timezone
from datetime import timedelta
from asgiref.sync import async_to_sync
import json
import logging
import asyncio

logger = logging.getLogger(__name__)

from .models import LLMAnalysis, UserRecommendation, AlertAnalysis, AreaUsagePattern, GeneratedContent, ChatSession, ChatMessage
from .serializers import (
    LLMAnalysisSerializer, UserRecommendationSerializer,
    AlertAnalysisSerializer, AreaUsagePatternSerializer, GeneratedContentSerializer,
    ChatSessionSerializer, ChatSessionDetailSerializer, ChatMessageSerializer
)
from webapi.models import Area, Alert, CustomUser
from .tasks import (
    analyze_area_data, analyze_alert,
    generate_area_usage_pattern, generate_personalized_recommendations
)
from .agent import get_agent_response
from .memory import ChatMemoryStore
from .utils import get_model_info


class LLMAnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LLMAnalysis.objects.all().order_by('-timestamp')
    serializer_class = LLMAnalysisSerializer

    @action(detail=True, methods=['post'], url_path='analyze')
    def analyze_area(self, request, pk=None):
        try:
            area = Area.objects.get(pk=pk)
        except Area.DoesNotExist:
            return Response({"error": "Area not found"}, status=status.HTTP_404_NOT_FOUND)

        recent_analysis = self.get_queryset().filter(
            area=area,
            timestamp__gte=timezone.now() - timedelta(hours=1)
        ).first()

        if recent_analysis:
            serializer = self.get_serializer(recent_analysis)
            return Response(serializer.data)

        analyze_area_data.delay(area.id)

        return Response({"message": "Analysis task has been started. Please check back later for the result."}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['get'], url_path='latest-analysis')
    def latest_analysis(self, request, pk=None):
        try:
            area = Area.objects.get(pk=pk)
        except Area.DoesNotExist:
            return Response({"error": "Area not found"}, status=status.HTTP_404_NOT_FOUND)

        latest_analysis = self.get_queryset().filter(area=area).first()

        if not latest_analysis:
            return Response({"message": "No analysis found for this area."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(latest_analysis)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='areas/(?P<area_id>[^/.]+)/analyses')
    def analyses_by_area(self, request, area_id=None):
        try:
            area = Area.objects.get(pk=area_id)
        except Area.DoesNotExist:
            return Response({"error": "Area not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            limit = int(request.query_params.get('limit', 10))
        except ValueError:
            limit = 10

        qs = self.get_queryset().filter(area=area).order_by('-timestamp')[:max(1, min(limit, 100))]
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class UserRecommendationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UserRecommendation.objects.all().order_by('-timestamp')
    serializer_class = UserRecommendationSerializer
    
    @action(detail=False, methods=['get'], url_path='user/(?P<user_id>[^/.]+)')
    def get_user_recommendations(self, request, user_id=None):
        try:
            user = CustomUser.objects.get(pk=user_id)
        except CustomUser.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        
        recommendations = self.get_queryset().filter(user=user).order_by('-timestamp')[:5]
        
        if not recommendations.exists() or recommendations.first().timestamp < timezone.now() - timedelta(days=1):
            generate_personalized_recommendations.delay()
            
            if not recommendations.exists():
                return Response({
                    "message": "正在为您生成个性化推荐，请稍后再试",
                    "status": "generating"
                }, status=status.HTTP_202_ACCEPTED)
        
        serializer = self.get_serializer(recommendations, many=True)
        return Response(serializer.data)


class AlertAnalysisViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AlertAnalysis.objects.all().order_by('-timestamp')
    serializer_class = AlertAnalysisSerializer
    
    @action(detail=False, methods=['get'], url_path='alert/(?P<alert_id>[^/.]+)')
    def get_alert_analysis(self, request, alert_id=None):
        try:
            alert = Alert.objects.get(pk=alert_id)
        except Alert.DoesNotExist:
            return Response({"error": "Alert not found"}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            analysis = self.get_queryset().get(alert=alert)
        except AlertAnalysis.DoesNotExist:
            analyze_alert.delay(alert.id)
            return Response({
                "message": "正在为该告警生成分析，请稍后再试",
                "status": "analyzing"
            }, status=status.HTTP_202_ACCEPTED)
        
        serializer = self.get_serializer(analysis)
        return Response(serializer.data)


class AreaUsagePatternViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AreaUsagePattern.objects.all()
    serializer_class = AreaUsagePatternSerializer
    
    @action(detail=False, methods=['get'], url_path='area/(?P<area_id>[^/.]+)')
    def get_area_pattern(self, request, area_id=None):
        try:
            area = Area.objects.get(pk=area_id)
        except Area.DoesNotExist:
            return Response({"error": "Area not found"}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            pattern = self.get_queryset().get(area=area)
            
            if pattern.last_updated < timezone.now() - timedelta(days=7):
                generate_area_usage_pattern.delay(area.id)
                return Response({
                    "message": "区域使用模式分析正在更新，返回当前可用数据",
                    "status": "updating",
                    "data": self.get_serializer(pattern).data
                })
            
            serializer = self.get_serializer(pattern)
            return Response(serializer.data)
            
        except AreaUsagePattern.DoesNotExist:
            generate_area_usage_pattern.delay(area.id)
            return Response({
                "message": "正在为该区域生成使用模式分析，请稍后再试",
                "status": "generating"
            }, status=status.HTTP_202_ACCEPTED)


class GeneratedContentViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = GeneratedContent.objects.all().order_by('-generated_at')
    serializer_class = GeneratedContentSerializer
    
    @action(detail=False, methods=['get'], url_path='area/(?P<area_id>[^/.]+)/notices')
    def get_area_notices(self, request, area_id=None):
        try:
            area = Area.objects.get(pk=area_id)
        except Area.DoesNotExist:
            return Response({"error": "Area not found"}, status=status.HTTP_404_NOT_FOUND)
        
        notices = self.get_queryset().filter(
            content_type='notice',
            related_area=area
        ).order_by('-generated_at')[:5]
        
        serializer = self.get_serializer(notices, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'], url_path='generate/notice')
    def generate_notice(self, request):
        area_id = request.data.get('area_id')
        notice_type = request.data.get('notice_type', 'status')
        
        if not area_id:
            return Response({"error": "Area ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            area = Area.objects.get(pk=area_id)
        except Area.DoesNotExist:
            return Response({"error": "Area not found"}, status=status.HTTP_404_NOT_FOUND)
        
        # 收集区域实际数据
        node = area.bound_node
        area_data = {
            "area_name": area.name,
            "building": area.type.name,
            "floor": area.floor,
            "capacity": area.capacity,
            "current_count": node.detected_count if node else 0,
            "temperature": node.temperature if node else None,
            "humidity": node.humidity if node else None,
        }
        
        # 获取最近的告警（如果是告警通知类型）
        recent_alerts = []
        if notice_type == "alert":
            alerts = Alert.objects.filter(area=area, solved=False).order_by('-timestamp')[:3]
            recent_alerts = [{"type": a.alert_type, "grade": a.grade, "message": a.message} for a in alerts]
            area_data["recent_alerts"] = recent_alerts
        
        # 构建 LLM 请求
        from .utils import run_llm_with_retry
        from langchain.schema import SystemMessage, HumanMessage
        import asyncio
        
        notice_type_desc = {
            "status": "区域状态通知（告知师生当前区域的环境和人流情况）",
            "alert": "告警通知（告知师生需要注意的安全/环境异常）",
            "maintenance": "维护通知（告知师生设备维护计划和影响）",
        }.get(notice_type, "通用通知")
        
        system_msg = SystemMessage(content=(
            "你是智慧校园公告撰写助手。请根据提供的区域实时数据，生成一条简洁、专业、友好的校园公告。"
            "公告应包含标题和正文两部分，用 '---' 分隔。"
            "标题不超过20字，正文不超过150字。语言要正式但亲切，适合校园师生阅读。"
            "必须基于实际数据撰写，不要编造不存在的信息。"
        ))
        human_msg = HumanMessage(content=(
            f"通知类型：{notice_type_desc}\n"
            f"区域数据：{json.dumps(area_data, ensure_ascii=False)}\n"
            f"请生成公告（标题---正文 格式）："
        ))
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    run_llm_with_retry([system_msg, human_msg], temperature=0.5, model_type="fast")
                )
            finally:
                loop.close()
            
            # 解析 LLM 返回的标题和正文
            if '---' in result:
                parts = result.split('---', 1)
                title = parts[0].strip().strip('#').strip()
                content = parts[1].strip()
            else:
                title = f"{area.name}{notice_type_desc[:4]}"
                content = result.strip()
            
            # 限制长度
            title = title[:200]
            
        except Exception as llm_err:
            logger.warning(f"LLM生成通知失败，使用兜底模板: {llm_err}")
            # 兜底：基于实际数据的模板
            count = area_data["current_count"]
            temp = area_data.get("temperature")
            title = f"{area.name}状态通知"
            content = f"{area.name}当前在场人数{count}人"
            if area.capacity > 0:
                content += f"（容量{area.capacity}人，使用率{round(count/area.capacity*100)}%）"
            if temp is not None:
                content += f"，温度{temp}°C"
            content += "。"
        
        generated_content = GeneratedContent.objects.create(
            content_type='notice',
            title=title,
            content=content,
            related_area=area,
            prompt_used=f"LLM生成{notice_type}类型公告 - {area.name}"
        )
        
        serializer = self.get_serializer(generated_content)
        return Response(serializer.data)


class AgentChatView(View):
    async def post(self, request, *args, **kwargs):
        body_bytes = request.body
        try:
            data = json.loads(body_bytes)
        except json.JSONDecodeError:
            return StreamingHttpResponse(
                json.dumps({"error": "Invalid JSON"}),
                status=400,
                content_type="application/json"
            )

        user_message = data.get("message")
        chat_history = data.get("history", []) or []
        model_type = data.get("model_type", "default")
        session_id = data.get("session_id")  # 前端传入的会话ID

        if not user_message:
            return StreamingHttpResponse(
                json.dumps({"error": "Message not provided"}),
                status=400,
                content_type="application/json"
            )

        # 如果有 session_id，从持久化存储加载历史
        if session_id:
            # 获取用户（如果已认证）
            user = request.user if hasattr(request, 'user') and request.user.is_authenticated else None
            
            # 如果前端没有传 history，从数据库加载
            if not chat_history:
                stored_history = ChatMemoryStore.get_history(session_id)
                chat_history = [{"role": h["role"], "content": h["content"]} for h in stored_history]
            
            # 持久化用户消息
            ChatMemoryStore.append(
                session_id=session_id,
                role="user",
                content=user_message,
                user=user,
                model_type=model_type
            )

        async def stream_generator():
            full_response = ""
            try:
                async for chunk in get_agent_response(user_message, chat_history, model_type=model_type):
                    data_out = chunk if isinstance(chunk, str) else json.dumps(chunk, ensure_ascii=False)
                    
                    # 收集 content 类型的文本用于持久化
                    try:
                        parsed = json.loads(data_out) if isinstance(data_out, str) else data_out
                        if isinstance(parsed, dict) and parsed.get("type") == "content":
                            full_response += parsed.get("text", "")
                    except (json.JSONDecodeError, TypeError):
                        pass
                    
                    yield f"data: {data_out}\n\n"
                    await asyncio.sleep(0)
            except Exception as e:
                import traceback
                traceback_str = traceback.format_exc()
                logger.error(f"Agent响应生成失败: {str(e)}\n{traceback_str}")
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            finally:
                # 持久化 AI 响应
                if session_id and full_response.strip():
                    try:
                        from channels.db import database_sync_to_async
                        await database_sync_to_async(ChatMemoryStore.append)(
                            session_id=session_id,
                            role="assistant",
                            content=full_response.strip(),
                            model_type=model_type
                        )
                    except Exception as persist_err:
                        logger.warning(f"持久化AI响应失败: {persist_err}")
                
                yield "data: [DONE]\n\n"
                await asyncio.sleep(0)

        # 创建响应对象并设置关键的流式传输头部
        response = StreamingHttpResponse(stream_generator(), content_type="text/event-stream")
        
        # 防止缓冲的关键头部
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate, no-transform'
        response['Pragma'] = 'no-cache'
        response['Expires'] = '0'
        response['X-Accel-Buffering'] = 'no'  # 禁用nginx缓冲
        response['Connection'] = 'keep-alive'
        
        return response


class ChatSessionListView(APIView):
    """获取当前用户的对话会话列表"""
    
    def get(self, request):
        user = request.user if request.user.is_authenticated else None
        if not user:
            return Response({"error": "请先登录"}, status=status.HTTP_401_UNAUTHORIZED)
        
        sessions = ChatSession.objects.filter(
            user=user, 
            is_archived=False
        ).order_by('-updated_at')[:50]
        
        serializer = ChatSessionSerializer(sessions, many=True)
        return Response(serializer.data)


class ChatSessionDetailView(APIView):
    """获取单个会话的详细信息（含消息列表）"""
    
    def get(self, request, session_id):
        try:
            session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            return Response({"error": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        
        # 检查权限：只能查看自己的会话
        if session.user and request.user.is_authenticated and session.user != request.user:
            return Response({"error": "无权访问此会话"}, status=status.HTTP_403_FORBIDDEN)
        
        serializer = ChatSessionDetailSerializer(session)
        return Response(serializer.data)
    
    def delete(self, request, session_id):
        """删除会话"""
        try:
            session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            return Response({"error": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        
        if session.user and request.user.is_authenticated and session.user != request.user:
            return Response({"error": "无权删除此会话"}, status=status.HTTP_403_FORBIDDEN)
        
        ChatMemoryStore.delete_session(session_id)
        return Response({"message": "会话已删除"}, status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, session_id):
        """更新会话标题"""
        try:
            session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            return Response({"error": "会话不存在"}, status=status.HTTP_404_NOT_FOUND)
        
        if session.user and request.user.is_authenticated and session.user != request.user:
            return Response({"error": "无权修改此会话"}, status=status.HTTP_403_FORBIDDEN)
        
        title = request.data.get('title')
        if title:
            session.title = title[:200]
            session.save(update_fields=['title'])
        
        serializer = ChatSessionSerializer(session)
        return Response(serializer.data)