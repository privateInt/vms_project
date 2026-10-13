//go:build !linux

package credentialcrypto

// Other operating systems require a reviewed equivalent of the Linux loader.
func LoadKeyBundleFile(string) (*Keyring, error) { return nil, ErrKeyFile }
