import json
import logging
import pprint
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MonnifyController(http.Controller):
    _return_url = "/payment/monnify/return"


    @http.route(_return_url, type='http', auth='public', csrf=False, methods=['GET'])
    def monnify_return_checkout(self, **kwargs):
        """Handle Monnify payment return after customer completes payment"""
        _logger.info("Monnify return - Received data:\n%s", pprint.pformat(kwargs))
        
        payment_reference = kwargs.get('paymentReference')
        if not payment_reference:
            _logger.error('No payment reference received from Monnify')
            return request.redirect('/payment/status')
        
        # Find the transaction
        transaction = request.env['payment.transaction'].sudo().search([
            ('reference', '=', payment_reference),
            ('provider_code', '=', 'monnify')
        ], limit=1)
        
        if not transaction:
            _logger.error('No transaction found for reference: %s', payment_reference)
            return request.redirect('/payment/status')
        
        # Create notification data with what we have
        notification_data = {
            'paymentReference': payment_reference,
            # Don't include transactionReference here since we don't have it from the redirect
            # The _process_notification_data method will use the stored one
        }
        
        try:
            # Process the notification - this will use the stored monnify_transaction_reference
            transaction._process_notification_data(notification_data)
            _logger.info('Successfully processed return for transaction %s', payment_reference)
        except Exception as e:
            _logger.error('Error processing Monnify return for %s: %s', payment_reference, str(e))
        
        return request.redirect('/payment/status')