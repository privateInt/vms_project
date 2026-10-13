package contracts

import (
	"encoding/json"
	"fmt"
	"math"
	"testing"
)

func TestSourceDeleteStrictJSON(t *testing.T) {
	for _, version := range []int64{1, 9007199254740993, math.MaxInt64} {
		body := fmt.Sprintf(`{"expected_version":%d,"\u0073chema_version":"\u00761"}`, version)
		var input SourceDelete
		if err := json.Unmarshal([]byte(body), &input); err != nil || input.ExpectedVersion != version || len(input.Validate()) != 0 {
			t.Fatal("exact integer/escaped field failed", input, err)
		}
	}
	for _, body := range []string{
		`null`, `[]`, `1`, `true`, `"text"`, `{} {}`, `{"schema_version":`,
		`{"expected_version":null}`, `{"expected_version":"1"}`, `{"expected_version":true}`, `{"expected_version":[]}`, `{"expected_version":{}}`,
		`{"expected_version":1.0}`, `{"expected_version":1e0}`, `{"expected_version":9223372036854775808}`, `{"expected_version":-9223372036854775809}`,
		`{"schema_version":null}`, `{"schema_version":1}`, `{"schema_version":false}`,
		`{"schema_version":"v1","schema_version":"v1"}`, `{"schema_version":"v1","\u0073chema_version":"v1"}`,
		`{"expected_version":1,"expected_version":1}`, `{"expected_version":1,"\u0065xpected_version":1}`,
		`{"Schema_Version":"v1"}`, `{"Expected_Version":1}`, `{"display_name":"name"}`, `{"source_id":"id"}`,
		`{"force":true}`, `{"cascade":true}`, `{"purge":true}`, `{"restore":true}`,
		`{"schema_version":"bad` + string([]byte{0xff}) + `"}`,
	} {
		var input SourceDelete
		if json.Unmarshal([]byte(body), &input) == nil {
			t.Fatalf("ambiguous JSON accepted: %q", body)
		}
	}
	for _, body := range []string{`{}`, `{"schema_version":"v1"}`, `{"expected_version":1}`, `{"schema_version":"v2","expected_version":1}`, `{"schema_version":"v1","expected_version":0}`, `{"schema_version":"v1","expected_version":-9223372036854775808}`} {
		var input SourceDelete
		if json.Unmarshal([]byte(body), &input) != nil || len(input.Validate()) == 0 {
			t.Fatal("semantic error classification", body)
		}
	}
}
