package credentialcrypto

// ProtectedBundleReceipt describes the exact bytes that this immutable ring
// owns. Only the protected file loader can populate it. ParseKeyBundle never
// manufactures filesystem evidence. The receipt is not a current path check,
// signature, restore fence or permission to use any key.
func (k *Keyring) ProtectedBundleReceipt() (sha256 string, readOnlyMount bool, err error) {
	if k == nil || k.bundleSHA256 == "" {
		return "", false, ErrKeyFile
	}
	return k.bundleSHA256, k.readOnlyMount, nil
}
