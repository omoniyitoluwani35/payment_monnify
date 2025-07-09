# -*- coding: utf-8 -*-
{
    'name': 'Monnify Payment Gateway',
    'version': '18.0.2.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 1,
    'summary': 'Monnify Payment Gateway Integration for Odoo',
    'description': """
        Monnify Payment Gateway
        =======================
        This module integrates Monnify payment gateway with Odoo.
        
        Features:
        - Online payments via Monnify
        - Support for card and bank transfer payments
        - Automatic payment validation
        - Webhook support for real-time updates
    """,
    'author': 'Omoniyi Toluwani ',
    'website': 'https://github.com/omoniyitoluwani35',
    'depends': ['payment'],
    'data': [
        'views/payment_monnify_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_provider_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}


