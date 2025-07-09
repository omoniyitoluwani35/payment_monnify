import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    monnify_transaction_reference = fields.Char(
        string='Monnify Transaction Reference',
        readonly=True,
        help="Reference of the transaction as stored by Monnify"
    )

    def _get_specific_rendering_values(self, processing_values):
        """Override to add Monnify-specific rendering values"""
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'monnify':
            return res

        # Prepare Monnify transaction data
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return_url = f"{base_url}/payment/monnify/return"
        
        transaction_data = {
            'amount': float(self.amount),
            'customerName': self.partner_name or self.partner_id.name,
            'customerEmail': self.partner_email or self.partner_id.email,
            'paymentReference': self.reference,
            'paymentDescription': f'Payment for {self.reference}',
            'contractCode': self.provider_id.monnify_contract_code,
            'redirectUrl': return_url,
            'currencyCode': self.currency_id.name,
            'paymentMethods': ['CARD', 'ACCOUNT_TRANSFER']
        }

        try:
            # Get access token
            access_token = self.provider_id._monnify_fetch_access_token()
            
            # Initialize transaction with Monnify
            urls = self.provider_id._get_monnify_urls()
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                urls['init_transaction_url'], 
                json=transaction_data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()

            if result.get('requestSuccessful'):
                self.monnify_transaction_reference = result['responseBody']['transactionReference']
                return {
                    'api_url': result['responseBody']['checkoutUrl'],
                    'url_params': {
                        'paymentReference': self.reference,
                        'amount': self.amount,
                        'currencyCode': self.currency_id.name,
                        'transactionReference': result['responseBody']['transactionReference'],
                    }
                }
            else:
                error_msg = result.get('responseMessage', 'Transaction initialization failed')
                raise ValidationError(_('Monnify Error: %s') % error_msg)

        except requests.exceptions.RequestException as e:
            _logger.error('Monnify API request failed: %s', str(e))
            raise ValidationError(_('Payment service unavailable. Please try again later.'))
        except Exception as e:
            _logger.error('Monnify transaction initialization failed: %s', str(e))
            raise ValidationError(_('Payment initialization failed: %s') % str(e))

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """Override to handle Monnify notification data"""
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'monnify' or len(tx) == 1:
            return tx

        # Try to find transaction by reference
        reference = notification_data.get('paymentReference')
        if reference:
            tx = self.search([
                ('reference', '=', reference), 
                ('provider_code', '=', 'monnify')
            ])
        
        # If not found by reference, try by Monnify transaction reference
        if not tx:
            monnify_ref = notification_data.get('transactionReference')
            if monnify_ref:
                tx = self.search([
                    ('monnify_transaction_reference', '=', monnify_ref),
                    ('provider_code', '=', 'monnify')
                ])
        
        if not tx:
            raise ValidationError(
                _("Monnify: No transaction found matching reference %s.") % 
                (reference or notification_data.get('transactionReference', 'Unknown'))
            )
        
        return tx

    def _process_notification_data(self, notification_data):
        """Override to handle Monnify notification processing"""
        super()._process_notification_data(notification_data)
        if self.provider_code != 'monnify':
            return

        transaction_reference = notification_data.get('transactionReference')

        # Store Monnify transaction reference if not already stored
        if transaction_reference and not self.monnify_transaction_reference:
            self.monnify_transaction_reference = transaction_reference

        # Verify with Monnify API
        monnify_ref_to_verify = self.monnify_transaction_reference or transaction_reference
    
        if not monnify_ref_to_verify:
            _logger.error('No Monnify transaction reference available for verification of %s', self.reference)
            self._set_error(_('Transaction verification failed - no reference'))
            return

        # Verify with Monnify API
        verification_result = self._monnify_verify_transaction(monnify_ref_to_verify)
        
        if verification_result:
            verified_status = verification_result.get('paymentStatus', '').upper()
            self._process_verified_status(verified_status, verification_result)
        else:
            # If verification fails, use notification status as fallback
            _logger.warning('Transaction verification failed for %s, using notification status', self.reference)
            payment_status = notification_data.get('paymentStatus', '').upper()
            if payment_status == 'PAID':
                self._set_done()
            elif payment_status in ['FAILED', 'CANCELLED']:
                self._set_canceled()
            else:
                self._set_error(_('Transaction verification failed'))

    def _process_verified_status(self, verified_status, verification_result):
        """Process verified status from Monnify API"""
        if verified_status == 'PAID':
            self._set_done()
            # Check for amount mismatch
            verified_amount = verification_result.get('amountPaid')
            if verified_amount and float(verified_amount) != self.amount:
                _logger.warning(
                    'Amount mismatch for transaction %s. Expected: %s, Verified: %s',
                    self.reference, self.amount, verified_amount
                )
        elif verified_status in ['FAILED', 'CANCELLED', 'EXPIRED']:
            self._set_canceled()
        elif verified_status in ['PENDING', 'OVERPAID', 'PARTIALLY_PAID']:
            self._set_canceled()
        else:
            _logger.warning('Unknown payment status from Monnify: %s', verified_status)
            self._set_canceled()
                
    def _monnify_verify_transaction(self, transaction_reference):
        """Verify transaction status with Monnify API"""
        if not transaction_reference:
            _logger.error('No transaction reference provided for verification')
            return False
            
        try:
            # Get access token
            access_token = self.provider_id._monnify_fetch_access_token()
            
            # Build verification URL
            urls = self.provider_id._get_monnify_urls()
            verify_url = f"{urls['verify_transaction_url']}?transactionReference={transaction_reference}"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            response = requests.get(verify_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            if result.get('requestSuccessful'):
                response_body = result.get('responseBody', {})
                _logger.info(
                    'Monnify transaction %s verification successful. Status: %s',
                    transaction_reference, 
                    response_body.get('paymentStatus')
                )
                return response_body
            else:
                _logger.error(
                    'Monnify transaction verification failed: %s',
                    result.get('responseMessage', 'Unknown error')
                )
                return False
            
        except requests.exceptions.RequestException as e:
            _logger.error('Monnify verification API request failed: %s', str(e))
            return False
        except Exception as e:
            _logger.error('Unexpected error in Monnify transaction verification: %s', str(e))
            return False