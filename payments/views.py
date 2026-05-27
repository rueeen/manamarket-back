from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.generics import RetrieveAPIView
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import is_admin_user, is_worker_user
from orders.models import Order

from .models import PaymentTransaction, SalesReceipt
from .serializers import SalesReceiptSerializer, WebpayCommitSerializer, WebpayCreateSerializer
from .services import (
    commit_webpay_transaction,
    create_webpay_transaction,
    finalize_paid_order,
    release_order_stock_reservation,
    validate_order_for_webpay_commit,
)


class WebpayCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        s = WebpayCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            order = Order.objects.get(pk=s.validated_data['order_id'])
        except Order.DoesNotExist:
            return Response({'detail': 'Orden no encontrada.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            payment, response = create_webpay_transaction(order, request.user)
        except ValidationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'token': payment.token, 'url': response.get('url'), 'order_id': order.id})


class WebpayCommitView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    FINAL_STATUSES = {
        PaymentTransaction.Status.AUTHORIZED,
        PaymentTransaction.Status.FAILED,
        PaymentTransaction.Status.REJECTED,
        PaymentTransaction.Status.CANCELLED,
        PaymentTransaction.Status.ERROR,
    }

    def _serialize_payment(self, payment, already_committed=False, detail=None):
        payload = {
            'status': payment.raw_response.get('status', payment.status.upper()),
            'response_code': payment.response_code,
            'buy_order': payment.buy_order,
            'session_id': payment.session_id,
            'amount': payment.amount_clp,
            'authorization_code': payment.authorization_code,
            'payment_type_code': payment.payment_type_code,
            'card_detail': {'card_number': payment.card_last_digits},
            'transaction_date': payment.transaction_date,
            'order_id': payment.order_id,
            'already_committed': already_committed,
        }
        if detail:
            payload['detail'] = detail
        return payload

    def post(self, request):
        s = WebpayCommitSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        token = s.validated_data['token']
        try:
            with transaction.atomic():
                payment = PaymentTransaction.objects.select_for_update().get(token=token)

                if payment.user_id != request.user.id:
                    return Response({'detail': 'No tienes permisos para confirmar esta transacción.'}, status=status.HTTP_403_FORBIDDEN)

                if payment.status in self.FINAL_STATUSES:
                    return Response(self._serialize_payment(payment, already_committed=True))

                validate_order_for_webpay_commit(payment.order)

                try:
                    response = commit_webpay_transaction(token)
                except ValidationError as exc:
                    message = str(exc)
                    if 'Transaction already locked by another process' in message:
                        payment.refresh_from_db()
                        if payment.status in self.FINAL_STATUSES:
                            return Response(self._serialize_payment(
                                payment,
                                already_committed=True,
                                detail='La transacción ya está siendo procesada o ya fue confirmada. Revisa el estado de la orden.',
                            ))
                        return Response({
                            'detail': 'La transacción ya está siendo procesada o ya fue confirmada. Revisa el estado de la orden.'
                        }, status=status.HTTP_409_CONFLICT)
                    raise

                payment.raw_response = response
                payment.authorization_code = response.get('authorization_code', '')
                payment.payment_type_code = response.get('payment_type_code', '')
                payment.response_code = response.get('response_code')
                payment.installments_number = response.get('installments_number') or 0
                payment.card_last_digits = (response.get('card_detail') or {}).get('card_number', '')
                payment.transaction_date = parse_datetime(response.get('transaction_date')) if response.get('transaction_date') else None

                is_authorized = response.get('response_code') == 0 and response.get('status') == 'AUTHORIZED'
                if is_authorized:
                    payment.status = PaymentTransaction.Status.AUTHORIZED
                    payment.save()
                    finalize_paid_order(payment.order, payment)
                    return Response(self._serialize_payment(payment, detail='Pago aprobado.'))

                if response.get('status') == 'FAILED':
                    payment.status = PaymentTransaction.Status.FAILED
                elif response.get('status') == 'CANCELLED':
                    payment.status = PaymentTransaction.Status.CANCELLED
                else:
                    payment.status = PaymentTransaction.Status.REJECTED
                payment.save()
                order = payment.order
                if order.status != Order.Status.PAID:
                    release_order_stock_reservation(order, payment=payment)
                    order.status = Order.Status.PAYMENT_FAILED
                    order.save(update_fields=['status', 'updated_at'])
                detail = 'Pago rechazado.' if payment.status in {PaymentTransaction.Status.FAILED, PaymentTransaction.Status.REJECTED} else 'Pago cancelado.'
                return Response(self._serialize_payment(payment, detail=detail), status=status.HTTP_200_OK)
        except PaymentTransaction.DoesNotExist:
            return Response({'detail': 'No existe una transacción local asociada al token entregado.'}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class SalesReceiptView(RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SalesReceiptSerializer
    lookup_url_kwarg = 'order_id'

    def get_object(self):
        order_id = self.kwargs[self.lookup_url_kwarg]

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise NotFound('Orden no encontrada.') from exc

        user = self.request.user
        if not (
            user == order.user
            or is_admin_user(user)
            or is_worker_user(user)
        ):
            raise PermissionDenied('No autorizado.')

        try:
            return order.sales_receipt
        except SalesReceipt.DoesNotExist as exc:
            raise NotFound('No existe comprobante para esta orden.') from exc
