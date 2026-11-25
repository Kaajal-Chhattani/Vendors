from django.urls import path

from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.ChatPageView.as_view(), name='chat-page'),
    path('send/', views.SendMessageView.as_view(), name='send-message'),
    path('new/', views.NewConversationView.as_view(), name='new-conversation'),
    path('new/<slug:agent_type>/', views.NewConversationView.as_view(), name='new-conversation-agent'),
    # path('graph/<str:agent_type>/', views.AgentGraphView.as_view(), name='agent-graph'),
    path('api/orders/status/', views.OrderStatusView.as_view(), name='order-status'),
    path('api/orders/list/', views.CustomerOrdersView.as_view(), name='order-list'),
    path('agents-ui/', views.AgentsUIPageView.as_view(), name='agents-ui'),
    path('api/document-notifications/', views.DocumentNotificationsView.as_view(), name='document-notifications'),
    path('api/temporal-auth/', views.TemporalAuthView.as_view(), name='temporal-auth'),
    path('api/process-runs/<str:workflow_id>/run-status/', views.ProcessRunStatusView.as_view(), name='process-run-status'),
    path('api/process-runs/<str:workflow_id>/stop/', views.ProcessRunStopView.as_view(), name='process-run-stop'),
    path('api/process-runs/<str:workflow_id>/restart/', views.ProcessRunRestartView.as_view(), name='process-run-restart'),
    path('api/process-runs/<str:workflow_id>/summary/', views.ProcessRunSummaryView.as_view(), name='process-run-summary'),
    path('api/documents/', views.DocumentListView.as_view(), name='document-list'),
    path('api/documents/<int:doc_id>/start/', views.DocumentStartStopView.as_view(action='start'), name='document-start'),
    path('api/documents/<int:doc_id>/stop/', views.DocumentStartStopView.as_view(action='stop'), name='document-stop'),
    path('api/documents/<int:doc_id>/run-status/', views.DocumentRunStatusView.as_view(), name='document-run-status'),
    path('api/documents/<int:doc_id>/summary/', views.DocumentSummaryView.as_view(), name='document-summary'),
    path('api/agents/', views.AgentListCreateView.as_view(), name='agent-list-create'),
    path('api/agents/<slug:agent_type>/call/', views.AgentCallView.as_view(), name='agent-call'),
    path('api/agents/<int:pk>/', views.AgentDetailView.as_view(), name='agent-detail'),
    path('files/<int:message_id>/', views.MessageFileView.as_view(), name='message-file'),
    path('api/files/', views.FileUploadView.as_view(), name='file-upload'),
    path('api/tools/', views.ToolListCreateView.as_view(), name='tool-list-create'),
    path('api/tools/<int:pk>/', views.ToolDetailView.as_view(), name='tool-detail'),
    path('<slug:agent_type>/', views.ChatPageView.as_view(), name='chat-agent'),
    path('<uuid:session_id>/messages/', views.ConversationMessagesView.as_view(), name='conversation-messages'),
]