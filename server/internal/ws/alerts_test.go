package ws

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/stretchr/testify/require"
)

func testRouter(deps AlertsDeps) *httptest.Server {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/ws/alerts", AlertsHandlerWithDeps(deps))
	return httptest.NewServer(r)
}

func dial(t *testing.T, url, token, headerToken string) (*websocket.Conn, *http.Response) {
	t.Helper()
	if token != "" {
		if strings.Contains(url, "?") {
			url += "&token=" + token
		} else {
			url += "?token=" + token
		}
	}
	header := http.Header{}
	if headerToken != "" {
		header.Set("X-Alert-Token", headerToken)
	}
	conn, resp, err := websocket.DefaultDialer.Dial(url, header)
	if err == nil {
		return conn, resp
	}
	return nil, resp
}

func TestAlertsOpenWithoutToken(t *testing.T) {
	hub := NewHub()
	srv := testRouter(AlertsDeps{Hub: hub, Logger: slog.New(slog.NewTextHandler(io.Discard, nil))})
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/alerts"
	conn, _ := dial(t, wsURL, "", "")
	require.NotNil(t, conn)
	require.Equal(t, 1, hub.Count())
	_ = conn.Close()
	require.Eventually(t, func() bool { return hub.Count() == 0 }, 3*time.Second, 10*time.Millisecond)
}

func TestAlertsTokenRequired(t *testing.T) {
	hub := NewHub()
	srv := testRouter(AlertsDeps{
		Hub: hub, Logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
		Token: "secret",
	})
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/alerts"

	// No token -> 403, not registered.
	_, resp := dial(t, wsURL, "", "")
	require.NotNil(t, resp)
	require.Equal(t, http.StatusForbidden, resp.StatusCode)
	require.Equal(t, 0, hub.Count())

	// Query token works (browsers).
	conn, _ := dial(t, wsURL, "secret", "")
	require.NotNil(t, conn)
	require.Equal(t, 1, hub.Count())
	_ = conn.Close()

	// Header token works (bots).
	conn2, _ := dial(t, wsURL, "", "secret")
	require.NotNil(t, conn2)
	_ = conn2.Close()
}

func TestAlertsReconnectFriendly(t *testing.T) {
	hub := NewHub()
	srv := testRouter(AlertsDeps{Hub: hub, Logger: slog.New(slog.NewTextHandler(io.Discard, nil))})
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/alerts"
	for i := 0; i < 3; i++ {
		conn, _ := dial(t, wsURL, "", "")
		require.NotNil(t, conn)
		_ = conn.Close()
		require.Eventually(t, func() bool { return hub.Count() == 0 }, 3*time.Second, 10*time.Millisecond)
	}
}
