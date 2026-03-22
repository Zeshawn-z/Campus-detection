from django.contrib import admin
from .models import (
    ChatSession, ChatMessage, LLMAnalysis, UserRecommendation,
    AlertAnalysis, AreaUsagePattern, GeneratedContent
)


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['session_id', 'user', 'title', 'model_type', 'is_archived', 'created_at', 'updated_at']
    list_filter = ['model_type', 'is_archived', 'created_at']
    search_fields = ['session_id', 'title', 'user__username']
    readonly_fields = ['session_id', 'created_at', 'updated_at']
    ordering = ['-updated_at']


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['session', 'role', 'short_content', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['content', 'session__session_id']
    readonly_fields = ['created_at']
    ordering = ['-created_at']

    def short_content(self, obj):
        return obj.content[:80] + '...' if len(obj.content) > 80 else obj.content
    short_content.short_description = '内容'


@admin.register(LLMAnalysis)
class LLMAnalysisAdmin(admin.ModelAdmin):
    list_display = ['area', 'alert_status', 'timestamp']
    list_filter = ['alert_status', 'timestamp']
    search_fields = ['area__name', 'analysis_text']
    ordering = ['-timestamp']


@admin.register(UserRecommendation)
class UserRecommendationAdmin(admin.ModelAdmin):
    list_display = ['user', 'area', 'score', 'clicked', 'timestamp']
    list_filter = ['clicked', 'timestamp']
    search_fields = ['user__username', 'area__name', 'reason']
    ordering = ['-timestamp']


@admin.register(AlertAnalysis)
class AlertAnalysisAdmin(admin.ModelAdmin):
    list_display = ['alert', 'priority_score', 'timestamp']
    list_filter = ['timestamp']
    ordering = ['-timestamp']


@admin.register(AreaUsagePattern)
class AreaUsagePatternAdmin(admin.ModelAdmin):
    list_display = ['area', 'average_duration', 'last_updated']
    search_fields = ['area__name', 'typical_user_groups']
    ordering = ['-last_updated']


@admin.register(GeneratedContent)
class GeneratedContentAdmin(admin.ModelAdmin):
    list_display = ['title', 'content_type', 'related_area', 'published', 'generated_at']
    list_filter = ['content_type', 'published', 'generated_at']
    search_fields = ['title', 'content']
    ordering = ['-generated_at']
