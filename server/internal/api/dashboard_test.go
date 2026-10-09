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
	require.Contains(t, body, "Inference Studio")
	require.Contains(t, body, "latest-image")
	require.Contains(t, body, "Detection stream")
	require.Contains(t, body, "score-meter")
	require.Contains(t, body, "Visual family · experimental")
	require.Contains(t, body, "Registered identity")
}

func TestHealthEndpoint(t *testing.T) {
	r := NewRouter(slog.New(slog.NewTextHandler(io.Discard, nil)), Handlers{})
	srv := httptest.NewServer(r)
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/health")
	require.NoError(t, err)
	defer resp.Body.Close()
	require.Equal(t, http.StatusOK, resp.StatusCode)
}
