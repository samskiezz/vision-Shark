from __future__ import annotations

STANDARD_DIDS={
    0xF180:'Boot software identification',
    0xF181:'Application software identification',
    0xF182:'Application data identification',
    0xF187:'Vehicle manufacturer spare part number',
    0xF188:'Vehicle manufacturer ECU software number',
    0xF189:'Vehicle manufacturer ECU software version',
    0xF18A:'System supplier identifier',
    0xF18B:'ECU manufacturing date',
    0xF18C:'ECU serial number',
    0xF190:'Vehicle identification number',
    0xF191:'Vehicle manufacturer ECU hardware number',
}

NRC={
    0x10:'generalReject',0x11:'serviceNotSupported',0x12:'subFunctionNotSupported',
    0x13:'incorrectMessageLengthOrInvalidFormat',0x14:'responseTooLong',
    0x21:'busyRepeatRequest',0x22:'conditionsNotCorrect',0x24:'requestSequenceError',
    0x31:'requestOutOfRange',0x33:'securityAccessDenied',0x35:'invalidKey',
    0x36:'exceedNumberOfAttempts',0x37:'requiredTimeDelayNotExpired',
    0x70:'uploadDownloadNotAccepted',0x71:'transferDataSuspended',0x72:'generalProgrammingFailure',
    0x73:'wrongBlockSequenceCounter',0x78:'requestCorrectlyReceivedResponsePending',
    0x7E:'subFunctionNotSupportedInActiveSession',0x7F:'serviceNotSupportedInActiveSession',
}


def did_name(did:int)->str|None:return STANDARD_DIDS.get(int(did))
def nrc_name(code:int)->str|None:return NRC.get(int(code))
def reference()->dict:return {'dids':{f'{k:04X}':v for k,v in STANDARD_DIDS.items()},'negative_response_codes':{f'{k:02X}':v for k,v in NRC.items()},'scope':'standards reference only; support is vehicle-specific'}
