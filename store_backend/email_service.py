import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def _send(subject, html_content, recipient_email, fail_silently=True):
    """Envía un correo HTML con texto plano como fallback."""
    if not recipient_email:
        logger.warning('Email no enviado: destinatario vacío. Asunto: %s', subject)
        return

    try:
        send_mail(
            subject=subject,
            message=strip_tags(html_content),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_content,
            fail_silently=False,
        )
        logger.info('Email enviado a %s: %s', recipient_email, subject)
    except Exception as exc:
        logger.error('Error enviando email a %s: %s', recipient_email, exc)
        if not fail_silently:
            raise


def send_order_confirmation(order):
    """Confirma al cliente que su pago fue aprobado."""
    user = order.user
    email = user.email
    name = user.get_full_name() or user.username
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')

    items_html = ''.join(
        f'<tr>'
        f'<td style="padding:8px;border-bottom:1px solid #eee">{item.product_name_snapshot}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:center">{item.quantity}</td>'
        f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:right">${item.subtotal_clp:,}</td>'
        f'</tr>'
        for item in order.items.all()
    )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#333">
      <div style="background:#1a1a2e;padding:24px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:24px">Manamarket</h1>
        <p style="color:#aaa;margin:8px 0 0">Tu tienda de Magic en Arica</p>
      </div>

      <div style="padding:32px 24px">
        <h2 style="color:#1a1a2e">¡Pago confirmado! 🎉</h2>
        <p>Hola <strong>{name}</strong>, recibimos tu pago correctamente.</p>

        <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:24px 0">
          <p style="margin:0 0 8px"><strong>Orden #{order.id}</strong></p>
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr style="background:#eee">
                <th style="padding:8px;text-align:left">Producto</th>
                <th style="padding:8px;text-align:center">Qty</th>
                <th style="padding:8px;text-align:right">Subtotal</th>
              </tr>
            </thead>
            <tbody>{items_html}</tbody>
            <tfoot>
              <tr>
                <td colspan="2" style="padding:8px;text-align:right"><strong>Envío:</strong></td>
                <td style="padding:8px;text-align:right">${order.shipping_clp:,}</td>
              </tr>
              <tr style="background:#1a1a2e;color:#fff">
                <td colspan="2" style="padding:10px;text-align:right"><strong>Total:</strong></td>
                <td style="padding:10px;text-align:right"><strong>${order.total_clp:,}</strong></td>
              </tr>
            </tfoot>
          </table>
        </div>

        <p>Dirección de envío: <strong>{order.shipping_street} {order.shipping_number}, {order.shipping_commune}</strong></p>

        <div style="text-align:center;margin:32px 0">
          <a href="{frontend_url}/pedidos"
             style="background:#1a1a2e;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold">
            Ver mi pedido
          </a>
        </div>
      </div>

      <div style="background:#f0f0f0;padding:16px;text-align:center;font-size:12px;color:#888">
        Manamarket · Arica, Chile · mana.market.arica@gmail.com
      </div>
    </div>
    """

    _send(f'✅ Orden #{order.id} confirmada — Manamarket', html, email)


def send_order_status_update(order):
    """Notifica al cliente cuando cambia el estado de su pedido."""
    user = order.user
    email = user.email
    name = user.get_full_name() or user.username
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')

    status_messages = {
        'processing': ('🔧 Tu pedido está siendo preparado', 'Estamos preparando tu pedido con cuidado.'),
        'shipped': ('🚚 Tu pedido fue enviado', 'Tu pedido está en camino. Pronto llegará a tu dirección.'),
        'delivered': ('📦 Tu pedido fue entregado', '¡Tu pedido fue entregado! Esperamos que disfrutes tus cartas.'),
        'completed': ('✅ Pedido completado', 'Tu pedido ha sido marcado como completado. ¡Gracias por comprar en Manamarket!'),
        'canceled': ('❌ Pedido cancelado', 'Tu pedido ha sido cancelado. Si tienes dudas contáctanos.'),
    }

    status_val = order.status
    subject_suffix, message = status_messages.get(
        status_val,
        ('Actualización de tu pedido', f'El estado de tu pedido cambió a: {order.get_status_display()}')
    )

    tracking_html = ''
    try:
        tracking = order.shipment
        if tracking.tracking_number:
            tracking_html = f"""
            <div style="background:#e8f4fd;border-radius:8px;padding:16px;margin:16px 0">
              <p style="margin:0"><strong>Número de seguimiento:</strong> {tracking.tracking_number}</p>
            </div>
            """
    except Exception:
        pass

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#333">
      <div style="background:#1a1a2e;padding:24px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:24px">Manamarket</h1>
      </div>

      <div style="padding:32px 24px">
        <h2 style="color:#1a1a2e">{subject_suffix}</h2>
        <p>Hola <strong>{name}</strong>,</p>
        <p>{message}</p>

        <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:16px 0">
          <p style="margin:0"><strong>Orden #{order.id}</strong> —
          Estado: <strong>{order.get_status_display()}</strong></p>
        </div>

        {tracking_html}

        <div style="text-align:center;margin:32px 0">
          <a href="{frontend_url}/pedidos"
             style="background:#1a1a2e;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold">
            Ver mi pedido
          </a>
        </div>
      </div>

      <div style="background:#f0f0f0;padding:16px;text-align:center;font-size:12px;color:#888">
        Manamarket · Arica, Chile · mana.market.arica@gmail.com
      </div>
    </div>
    """

    _send(f'Orden #{order.id}: {subject_suffix} — Manamarket', html, email)


def send_password_reset(user, reset_url):
    """Envía el link de recuperación de contraseña."""
    name = user.get_full_name() or user.username
    email = user.email

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;color:#333">
      <div style="background:#1a1a2e;padding:24px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:24px">Manamarket</h1>
      </div>

      <div style="padding:32px 24px">
        <h2 style="color:#1a1a2e">Recuperación de contraseña</h2>
        <p>Hola <strong>{name}</strong>,</p>
        <p>Recibimos una solicitud para restablecer la contraseña de tu cuenta.</p>
        <p>Haz clic en el botón para crear una nueva contraseña. Este enlace expira en <strong>1 hora</strong>.</p>

        <div style="text-align:center;margin:32px 0">
          <a href="{reset_url}"
             style="background:#1a1a2e;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold">
            Restablecer contraseña
          </a>
        </div>

        <p style="color:#888;font-size:13px">Si no solicitaste esto, ignora este correo. Tu contraseña no cambiará.</p>
        <p style="color:#888;font-size:12px;word-break:break-all">O copia este enlace: {reset_url}</p>
      </div>

      <div style="background:#f0f0f0;padding:16px;text-align:center;font-size:12px;color:#888">
        Manamarket · Arica, Chile · mana.market.arica@gmail.com
      </div>
    </div>
    """

    _send('Recuperación de contraseña — Manamarket', html, email)
