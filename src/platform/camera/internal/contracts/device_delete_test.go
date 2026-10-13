package contracts

import (
	"math"
	"testing"
)

func TestDeviceDeleteInternalCommand(t *testing.T) {
	for _, version := range []int64{1, math.MaxInt64} {
		if got := (DeviceDelete{SchemaVersion: "v1", ExpectedVersion: version}).Validate(); len(got) != 0 {
			t.Fatal(got)
		}
	}
	for _, input := range []DeviceDelete{{}, {SchemaVersion: "v2", ExpectedVersion: 1}, {SchemaVersion: "v1", ExpectedVersion: 0}, {SchemaVersion: "v1", ExpectedVersion: -1}} {
		if len(input.Validate()) == 0 {
			t.Fatal("invalid command accepted")
		}
	}
}
