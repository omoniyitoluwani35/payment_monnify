# -*- coding: utf-8 -*-
import json
import requests
import logging
import base64
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('monnify', "Monnify")], ondelete={'monnify': 'set default'}
    )
    monnify_api_key = fields.Char(
        string='API Key', 
        required_if_provider='monnify',
        groups='base.group_system',
        placeholder='API key'
    )
    monnify_secret_key = fields.Char(
        string='Secret Key', 
        required_if_provider='monnify',
        groups='base.group_system',
        placeholder='Secret key'
    )
    monnify_contract_code = fields.Char(
        string='Contract Code', 
        required_if_provider='monnify',
        groups='base.group_system',
        placeholder='Contract code'
    )
    monnify_base_url = fields.Char(
        string='Base URL',
        default='https://sandbox.monnify.com',
        required_if_provider='monnify'
    )

    def _should_build_inline_form(self, is_validation=False):
        """Monnify uses redirect flow to their checkout page."""
        self.ensure_one()
        if self.code != 'monnify':
            return super()._should_build_inline_form(is_validation=is_validation)
        return False
    
    def _compute_feature_support_fields(self):
        """Define supported features for Monnify provider."""
        super()._compute_feature_support_fields()
        if self.code == 'monnify':
            self.support_express_checkout = False
            self.support_manual_capture = False
            self.support_refund = False
            self.support_tokenization = False

    def _get_monnify_urls(self):
        base_url = self.monnify_base_url or 'https://sandbox.monnify.com'
        return {
            'auth_url': f"{base_url}/api/v1/auth/login",
            'init_transaction_url': f"{base_url}/api/v1/merchant/transactions/init-transaction",
            'verify_transaction_url': f"{base_url}/api/v1/merchant/transactions/query",
        }
    
    def _monnify_fetch_access_token(self):
        try:
            urls = self._get_monnify_urls()
            credentials = f"{self.monnify_api_key}:{self.monnify_secret_key}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/json'
            }
            
            response = requests.post(urls['auth_url'], headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('requestSuccessful'):
                return result['responseBody']['accessToken']
            else:
                raise UserError(_('Monnify authentication failed: %s') % result.get('responseMessage', 'Unknown error'))
                
        except requests.exceptions.RequestException as e:
            _logger.error('Monnify authentication error: %s', str(e))
            raise UserError(_('Failed to authenticate with Monnify: %s') % str(e))
    
    def _monnify_form_generate_values(self, values):
        """Generate payment form values for Monnify"""
        try:
            access_token = self._monnify_fetch_access_token()
            urls = self._get_monnify_urls()
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            return_url = f"{base_url}/payment/monnify/return"
            
            transaction_data = {
                'amount': float(values.get('amount', 0)),
                'customerName': values.get('partner_name', ''),
                'customerEmail': values.get('partner_email', ''),
                'paymentReference': values.get('reference', ''),
                'paymentDescription': values.get('reference', 'Payment'),
                'contractCode': self.monnify_contract_code,
                'redirectUrl': return_url,
                'currencyCode': values.get('currency', {}).get('name', 'NGN'),
                'paymentMethods': ['CARD', 'ACCOUNT_TRANSFER']
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
                payment_link = result['responseBody']['checkoutUrl']
                transaction_reference = result['responseBody']['transactionReference']
                
                # Store transaction reference for later verification
                payment_transaction = self.env['payment.transaction'].search([
                    ('reference', '=', values.get('reference'))
                ], limit=1)
                
                if payment_transaction:
                    payment_transaction.provider_reference = transaction_reference
                
                return {
                    'checkout_url': payment_link,
                    'transaction_reference': transaction_reference
                }
            else:
                error_msg = result.get('responseMessage', 'Unknown error occurred')
                _logger.error('Monnify transaction initialization failed: %s', error_msg)
                raise UserError(_('Payment initialization failed: %s') % error_msg)
                
        except requests.exceptions.RequestException as e:
            _logger.error('Monnify API request failed: %s', str(e))
            raise UserError(_('Payment service unavailable. Please try again later.'))
        except Exception as e:
            _logger.error('Unexpected error in Monnify payment: %s', str(e))
            raise UserError(_('An unexpected error occurred. Please try again.'))
    
    @api.model
    def _get_compatible_providers(self, *args, **kwargs):
        """Override to include Monnify in compatible providers"""
        providers = super()._get_compatible_providers(*args, **kwargs)
        return providers.filtered(lambda p: p.code != 'monnify') + providers.filtered(lambda p: p.code == 'monnify')
    
    def _get_redirect_form_view(self, is_validation=False):
        """Return the view of the template used to render the redirect form for Monnify."""
        self.ensure_one()
        if self.code != 'monnify':
            return super()._get_redirect_form_view(is_validation=is_validation)
        return self.env.ref('payment_monnify.redirect_form')
    
    def _get_default_payment_form_action_url(self):
        if self.code != 'monnify':
            return super()._get_default_payment_form_action_url()
        return '/payment/monnify/redirect'