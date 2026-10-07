package api

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestDashboardServesPage(t *testing.T) {
	r := NewRouter(slog.New(slog.NewTextHandler(io.Discard, nil)), Handlers{})
	srv := httptest.NewServer(r)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/")
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)
	require.Contains(t, resp.Header.Get("Content-Type"), "text/html")

	raw, err := io.ReadAll(resp.Body)
	require.NoError(t, err)
	body := string(raw)
	require.Contains(t, body, "/ws/alerts")
	require.Contains(t, body, ".badge.authorized")
	require.Contains(t, body, ".badge.unauthorized")
	require.Contains(t, body, ".badge.unidentified")
	require.Contains(t, body, "identity")
	require.Contains(t, body, "snapshot")
}

func TestHealthEndpoint(t *testing.T) {
	r := NewRouter(slog.New(slog.NewTextHandler(io.Discard, nil)), Handlers{})
	srv := httptest.NewServer(r)
	defer srv.Close()

	for _, path := range []string{"/health", "/healthz"} {
		resp, err := http.Get(srv.URL + path)
		require.NoError(t, err)
		defer resp.Body.Close()
		require.Equal(t, http.StatusOK, resp.StatusCode, path)
	}
}
