package credentialcrypto

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"testing"
)

func TestCredentialRestoreSuccessorMaterial(t *testing.T) {
	old := keyBundle{Format: 1, Encryption: keySet{Active: "enc-1111111111111111", Keys: map[string]string{"enc-1111111111111111": base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{1}, 32))}}, Idempotency: keySet{Active: "idem-2222222222222222", Keys: map[string]string{"idem-2222222222222222": base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{2}, 32))}}}
	parse := func(b keyBundle) *Keyring {
		raw, _ := json.Marshal(b)
		k, e := ParseKeyBundle(raw)
		if e != nil {
			t.Fatal(e)
		}
		return k
	}
	previous := parse(old)
	fresh := func() keyBundle {
		return keyBundle{1, keySet{"enc-3333333333333333", map[string]string{"enc-1111111111111111": old.Encryption.Keys[old.Encryption.Active], "enc-3333333333333333": base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{3}, 32))}}, old.Idempotency}
	}
	if parse(fresh()).CheckRestoreSuccessor(previous, previous) != nil {
		t.Fatal("valid successor denied")
	}
	cases := map[string]func(keyBundle) keyBundle{
		"missing history": func(b keyBundle) keyBundle { delete(b.Encryption.Keys, old.Encryption.Active); return b },
		"changed history": func(b keyBundle) keyBundle {
			b.Encryption.Keys[old.Encryption.Active] = base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{4}, 32))
			return b
		},
		"relabel material": func(b keyBundle) keyBundle {
			delete(b.Encryption.Keys, old.Encryption.Active)
			b.Encryption.Keys[b.Encryption.Active] = old.Encryption.Keys[old.Encryption.Active]
			return b
		},
		"old active": func(b keyBundle) keyBundle { b.Encryption.Active = old.Encryption.Active; return b },
	}
	for name, modify := range cases {
		t.Run(name, func(t *testing.T) {
			if parse(modify(fresh())).CheckRestoreSuccessor(previous, previous) == nil {
				t.Fatal("unsafe successor accepted")
			}
		})
	}
	var absent *Keyring
	if absent.CheckRestoreSuccessor(previous, previous) == nil || parse(fresh()).CheckRestoreSuccessor(nil, previous) == nil {
		t.Fatal("nil accepted")
	}
	// A key absent from the backup may still have been used after that snapshot.
	advanced := fresh()
	advancedRing := parse(advanced)
	if parse(fresh()).CheckRestoreSuccessor(advancedRing, previous) == nil {
		t.Fatal("post-snapshot used key accepted")
	}
	if !previous.HasHistoricalKeys(old.Encryption.Active, old.Idempotency.Active) || previous.HasHistoricalKeys("missing", old.Idempotency.Active) {
		t.Fatal("history availability invalid")
	}
}
