-- disable flutterwave payment provider
UPDATE payment_provider
   SET monnify_api_key = NULL,
       monnify_secret_key = NULL,
       monnify_contract_code = NULL;
