package credentialcrypto

// CheckRestoreSuccessor compares private material without exporting it. Both
// pre-fence and backup rings must come from trusted protected files. Retain all
// historical encryption/MAC material under the same IDs, keep the current MAC
// active, and require an independent encryption key absent from BOTH inputs.
// External seen-ID history and durable PREPARED remain separate requirements.
func (k *Keyring) CheckRestoreSuccessor(previous, backup *Keyring) error {
	if k == nil || previous == nil || backup == nil {
		return ErrKeyBundle
	}
	if k.activeIdempotency != previous.activeIdempotency {
		return ErrKeyBundle
	}
	fresh, ok := k.encryption[k.activeEncryption]
	if !ok {
		return ErrKeyBundle
	}
	for _, old := range []*Keyring{previous, backup} {
		if _, exists := old.encryption[k.activeEncryption]; exists {
			return ErrKeyBundle
		}
		for id, value := range old.encryption {
			if actual, exists := k.encryption[id]; !exists || actual != value || fresh == value {
				return ErrKeyBundle
			}
		}
		for id, value := range old.idempotency {
			if actual, exists := k.idempotency[id]; !exists || actual != value || fresh == value {
				return ErrKeyBundle
			}
		}
	}
	return nil
}

// HasHistoricalKeys reports only availability of IDs, never material.
func (k *Keyring) HasHistoricalKeys(encryptionID, idempotencyID string) bool {
	if k == nil {
		return false
	}
	_, enc := k.encryption[encryptionID]
	_, mac := k.idempotency[idempotencyID]
	return enc && mac
}
