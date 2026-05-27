from django.urls import path

from .views import SalesReceiptView, WebpayCommitView, WebpayCreateView

urlpatterns = [
    path('webpay/create/', WebpayCreateView.as_view()),
    path('webpay/commit/', WebpayCommitView.as_view()),
    path('receipts/<int:order_id>/', SalesReceiptView.as_view()),
]
