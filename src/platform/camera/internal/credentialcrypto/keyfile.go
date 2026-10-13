package credentialcrypto

import "errors"

// All loader failures are fixed diagnostics: neither paths nor file contents
// become an error cause available to a caller or logger.
var ErrKeyFile = errors.New("CREDENTIAL_KEY_FILE_UNAVAILABLE")
