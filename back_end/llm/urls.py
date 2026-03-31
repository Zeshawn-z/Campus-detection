from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    LLMAnalysisViewSet, UserRecommendationViewSet, AlertAnalysisViewSet,
    AreaUsagePatternViewSet, GeneratedContentViewSet, AgentChatView,
    ChatSessionListView, ChatSessionDetailView
)

router = DefaultRouter()
router.register(r'analysis', LLMAnalysisViewSet, basename='llmanalysis')
router.register(r'recommendations', UserRecommendationViewSet, basename='userrecommendation')
router.register(r'alert-analysis', AlertAnalysisViewSet, basename='alertanalysis')
router.register(r'usage-patterns', AreaUsagePatternViewSet, basename='areausagepattern')
router.register(r'generated-content', GeneratedContentViewSet, basename='generatedcontent')

from django.http import JsonResponse
from .utils import get_model_info

def model_info_view(request):
    return JsonResponse(get_model_info())

urlpatterns = [
    path('', include(router.urls)),
    path('chat/', AgentChatView.as_view(), name='agent-chat'),
    path('model-info/', model_info_view, name='model-info'),
    # 对话会话管理 API
    path('sessions/', ChatSessionListView.as_view(), name='chat-sessions'),
    path('sessions/<str:session_id>/', ChatSessionDetailView.as_view(), name='chat-session-detail'),
]