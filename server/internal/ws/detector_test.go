package ws

import (
	"testing"

	"drone-detect-app/server/internal/model"
)

func TestShouldEnqueueExport(t *testing.T) {
	cases := []struct {
		name           string
		result         string
		identifiedOnly bool
		want           bool
	}{
		{"identified passes the gate", model.IdentityIdentified, true, true},
		{"none is skipped", model.IdentityNone, true, false},
		{"ambiguous is skipped", model.IdentityAmbiguous, true, false},
		{"mismatch is skipped", model.IdentityMismatch, true, false},
		{"gate off exports everything", model.IdentityNone, false, true},
		{"gate off exports identified", model.IdentityIdentified, false, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := ShouldEnqueueExport(tc.result, tc.identifiedOnly); got != tc.want {
				t.Fatalf("ShouldEnqueueExport(%q, %v) = %v, want %v",
					tc.result, tc.identifiedOnly, got, tc.want)
			}
		})
	}
}
