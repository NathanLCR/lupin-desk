package com.nathanlucio.deskassistant;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Activity principal em tela cheia imersiva para o Anbernic RG406H.
 * Hospeda a interface web do Desk Assistant com suporte a microfone,
 * Gamepad API, certificado local autoassinado e ponte nativa AndroidBridge.
 */
public class MainActivity extends Activity {

    private static final String PREFS_NAME = "desk_assistant_prefs";
    private static final String KEY_SERVER_URL = "server_url";

    public static final String DEFAULT_USB_URL = "http://localhost:8000";
    public static final String DEFAULT_WIFI_URL = "https://192.168.0.125:8443";

    private static final String LOCAL_PROBE_HOST = "127.0.0.1";
    private static final int LOCAL_PROBE_PORT = 8000;
    private static final int PROBE_TIMEOUT_MS = 800;

    private static final int REQUEST_RECORD_AUDIO = 1001;
    private static final long MENU_BUTTON_AUTO_HIDE_MS = 3000L;
    private static final long DOUBLE_BACK_WINDOW_MS = 1500L;

    private FrameLayout rootLayout;
    private WebView webView;
    private TextView serverMenuButton;
    private SharedPreferences prefs;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService networkExecutor = Executors.newSingleThreadExecutor();

    private String currentUrl = DEFAULT_USB_URL;
    private boolean fallbackAttempted = false;
    private long lastBackPressMs = 0L;
    private PermissionRequest pendingPermissionRequest = null;

    private final Runnable fadeMenuButtonRunnable = () -> {
        if (serverMenuButton != null) {
            serverMenuButton.animate().alpha(0.22f).setDuration(350L).start();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Mantém a tela sempre ativa no uso como pet de mesa OLED.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= 28) {
            WindowManager.LayoutParams lp = getWindow().getAttributes();
            lp.layoutInDisplayCutoutMode =
                    WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(lp);
        }

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE);
        currentUrl = sanitizeServerUrl(prefs.getString(KEY_SERVER_URL, DEFAULT_USB_URL));
        if (currentUrl == null) {
            currentUrl = DEFAULT_USB_URL;
        }

        setupUi();
        enableImmersiveMode();
        requestAudioPermissionIfNeeded();
        resolveAndLoadInitialUrl();
    }

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    private void setupUi() {
        rootLayout = new FrameLayout(this);
        rootLayout.setBackgroundColor(Color.BLACK);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.BLACK);
        webView.setFocusable(true);
        webView.setFocusableInTouchMode(true);
        webView.setHapticFeedbackEnabled(true);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);

        webView.setWebViewClient(new DeskWebViewClient());
        webView.setWebChromeClient(new DeskWebChromeClient());
        webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");

        FrameLayout.LayoutParams webParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        );
        rootLayout.addView(webView, webParams);

        // Botão discreto no canto superior direito para menu de servidor (auto-ocultável em 3s).
        int sizePx = dpToPx(44);
        int marginPx = dpToPx(10);
        serverMenuButton = new TextView(this);
        serverMenuButton.setText("⚙");
        serverMenuButton.setTextColor(Color.parseColor("#D956DCFF"));
        serverMenuButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        serverMenuButton.setGravity(Gravity.CENTER);
        serverMenuButton.setContentDescription("Configurar servidor");

        GradientDrawable badgeBg = new GradientDrawable();
        badgeBg.setShape(GradientDrawable.OVAL);
        badgeBg.setColor(Color.parseColor("#880B0F16"));
        badgeBg.setStroke(dpToPx(1), Color.parseColor("#6656DCFF"));
        serverMenuButton.setBackground(badgeBg);

        FrameLayout.LayoutParams btnParams = new FrameLayout.LayoutParams(sizePx, sizePx);
        btnParams.gravity = Gravity.TOP | Gravity.END;
        btnParams.setMargins(marginPx, marginPx, marginPx, marginPx);

        serverMenuButton.setOnClickListener(v -> {
            revealMenuButtonTemporarily();
            openServerMenu();
        });
        serverMenuButton.setOnLongClickListener(v -> {
            revealMenuButtonTemporarily();
            openServerMenu();
            return true;
        });

        rootLayout.addView(serverMenuButton, btnParams);
        setContentView(rootLayout);
        revealMenuButtonTemporarily();
        webView.requestFocus();
    }

    private void revealMenuButtonTemporarily() {
        if (serverMenuButton == null) {
            return;
        }
        mainHandler.removeCallbacks(fadeMenuButtonRunnable);
        serverMenuButton.animate().cancel();
        serverMenuButton.setAlpha(0.8f);
        mainHandler.postDelayed(fadeMenuButtonRunnable, MENU_BUTTON_AUTO_HIDE_MS);
    }

    private int dpToPx(int dp) {
        return Math.round(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP,
                dp,
                getResources().getDisplayMetrics()
        ));
    }

    private void enableImmersiveMode() {
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                controller.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                );
            }
        } else {
            applyLegacyImmersiveFlags();
        }
    }

    @SuppressWarnings("deprecation")
    private void applyLegacyImmersiveFlags() {
        View decor = getWindow().getDecorView();
        decor.setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
        );
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            enableImmersiveMode();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
        enableImmersiveMode();
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            webView.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        mainHandler.removeCallbacksAndMessages(null);
        networkExecutor.shutdownNow();
        if (pendingPermissionRequest != null) {
            pendingPermissionRequest.deny();
            pendingPermissionRequest = null;
        }
        if (webView != null) {
            if (rootLayout != null) {
                rootLayout.removeView(webView);
            }
            webView.stopLoading();
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        // Nunca intercepta eventos vindos de controle/gamepad para não atrapalhar a Gamepad API.
        boolean fromGamepad = isGamepadEvent(event);
        if (!fromGamepad
                && event.getKeyCode() == KeyEvent.KEYCODE_BACK
                && event.getAction() == KeyEvent.ACTION_UP) {
            long now = System.currentTimeMillis();
            if (now - lastBackPressMs <= DOUBLE_BACK_WINDOW_MS) {
                lastBackPressMs = 0L;
                openServerMenu();
            } else {
                lastBackPressMs = now;
                Toast.makeText(
                        this,
                        "Pressione VOLTAR novamente para abrir o menu do servidor",
                        Toast.LENGTH_SHORT
                ).show();
            }
            return true;
        }
        return super.dispatchKeyEvent(event);
    }

    private static boolean isGamepadEvent(KeyEvent event) {
        int source = event.getSource();
        return (source & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
                || (source & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK;
    }

    private boolean hasAudioPermission() {
        return checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void requestAudioPermissionIfNeeded() {
        if (!hasAudioPermission()) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQUEST_RECORD_AUDIO);
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO && pendingPermissionRequest != null) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            PermissionRequest req = pendingPermissionRequest;
            pendingPermissionRequest = null;
            if (granted) {
                req.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            } else {
                req.deny();
            }
        }
    }

    private void resolveAndLoadInitialUrl() {
        String saved = sanitizeServerUrl(prefs.getString(KEY_SERVER_URL, null));
        if (saved != null && !DEFAULT_USB_URL.equals(saved)) {
            fallbackAttempted = false;
            loadServerUrl(saved);
            return;
        }

        // Faz probe rápido na porta 8000 local (túnel USB ADB); se indisponível, cai para Wi-Fi HTTPS.
        networkExecutor.execute(() -> {
            boolean usbTunnelReady = isTcpPortReachable(
                    LOCAL_PROBE_HOST,
                    LOCAL_PROBE_PORT,
                    PROBE_TIMEOUT_MS
            );
            String target = usbTunnelReady ? DEFAULT_USB_URL : DEFAULT_WIFI_URL;
            mainHandler.post(() -> {
                if (isFinishing() || isDestroyed() || webView == null) {
                    return;
                }
                fallbackAttempted = !usbTunnelReady;
                loadServerUrl(target);
            });
        });
    }

    private static boolean isTcpPortReachable(String host, int port, int timeoutMs) {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, port), timeoutMs);
            return true;
        } catch (IOException ignored) {
            return false;
        }
    }

    private void loadServerUrl(String url) {
        String cleanUrl = sanitizeServerUrl(url);
        if (cleanUrl == null || webView == null) {
            return;
        }
        currentUrl = cleanUrl;
        webView.loadUrl(cleanUrl);
    }

    private static String sanitizeServerUrl(String rawUrl) {
        if (rawUrl == null) {
            return null;
        }
        String trimmed = rawUrl.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        Uri parsed = Uri.parse(trimmed);
        String scheme = parsed.getScheme();
        String host = parsed.getHost();
        if (scheme == null || host == null || host.trim().isEmpty()) {
            return null;
        }
        String lowerScheme = scheme.toLowerCase(Locale.US);
        if (!"http".equals(lowerScheme) && !"https".equals(lowerScheme)) {
            return null;
        }
        return trimmed;
    }

    /**
     * Valida estritamente se o host é local ou pertence a uma faixa privada RFC 1918 / loopback.
     * Aceita apenas: localhost, 127.x.x.x, ::1, *.local, 10.x.x.x, 192.168.x.x, 172.16-31.x.x.
     */
    static boolean isPrivateOrLocalHost(String rawHost) {
        if (rawHost == null) {
            return false;
        }
        String host = rawHost.trim().toLowerCase(Locale.US);
        if (host.startsWith("[") && host.endsWith("]") && host.length() > 2) {
            host = host.substring(1, host.length() - 1);
        }
        if (host.isEmpty()) {
            return false;
        }
        if ("localhost".equals(host) || "::1".equals(host) || host.endsWith(".local")) {
            return true;
        }

        String[] parts = host.split("\\.");
        if (parts.length != 4) {
            return false;
        }
        int[] octets = new int[4];
        for (int i = 0; i < 4; i++) {
            try {
                int value = Integer.parseInt(parts[i]);
                if (value < 0 || value > 255) {
                    return false;
                }
                octets[i] = value;
            } catch (NumberFormatException e) {
                return false;
            }
        }

        int first = octets[0];
        int second = octets[1];
        if (first == 127) {
            return true;
        }
        if (first == 10) {
            return true;
        }
        if (first == 192 && second == 168) {
            return true;
        }
        return first == 172 && second >= 16 && second <= 31;
    }

    public void openServerMenu() {
        mainHandler.post(() -> {
            if (isFinishing() || isDestroyed()) {
                return;
            }
            revealMenuButtonTemporarily();
            String[] options = new String[]{
                    "USB ADB (" + DEFAULT_USB_URL + ")",
                    "Wi-Fi HTTPS (" + DEFAULT_WIFI_URL + ")",
                    "URL Customizada...",
                    "Recarregar Página"
            };
            new AlertDialog.Builder(MainActivity.this)
                    .setTitle("Servidor — Desk Assistant")
                    .setItems(options, (dialog, which) -> {
                        if (which == 0) {
                            saveAndLoadServerUrl(DEFAULT_USB_URL);
                        } else if (which == 1) {
                            saveAndLoadServerUrl(DEFAULT_WIFI_URL);
                        } else if (which == 2) {
                            showCustomUrlDialog();
                        } else if (which == 3) {
                            fallbackAttempted = false;
                            loadServerUrl(currentUrl);
                        }
                    })
                    .setNegativeButton("Fechar", null)
                    .show();
        });
    }

    private void showCustomUrlDialog() {
        EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setText(currentUrl);
        input.setSelection(input.getText().length());

        int pad = dpToPx(16);
        FrameLayout container = new FrameLayout(this);
        container.setPadding(pad, dpToPx(8), pad, 0);
        container.addView(input);

        new AlertDialog.Builder(this)
                .setTitle("URL do Servidor")
                .setView(container)
                .setPositiveButton("Conectar", (dialog, which) -> {
                    String entered = input.getText().toString();
                    String valid = sanitizeServerUrl(entered);
                    if (valid != null) {
                        saveAndLoadServerUrl(valid);
                    } else {
                        Toast.makeText(
                                this,
                                "URL inválida. Use http:// ou https://",
                                Toast.LENGTH_SHORT
                        ).show();
                    }
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    private void saveAndLoadServerUrl(String url) {
        String valid = sanitizeServerUrl(url);
        if (valid == null) {
            return;
        }
        prefs.edit().putString(KEY_SERVER_URL, valid).apply();
        fallbackAttempted = false;
        loadServerUrl(valid);
    }

    private void renderOfflineErrorPage(String failedUrl, String reason) {
        if (webView == null) {
            return;
        }
        String safeUrl = escapeHtml(failedUrl);
        String safeReason = escapeHtml(reason != null ? reason : "Sem resposta do servidor");
        String html = "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
                + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                + "<style>"
                + "html,body{margin:0;height:100%;background:#000;color:#e6faff;"
                + "font-family:sans-serif;display:flex;align-items:center;justify-content:center;}"
                + ".card{max-width:540px;padding:24px;text-align:center;"
                + "border:1px solid #56dcff44;border-radius:16px;background:#0b0f16;}"
                + "h2{color:#56dcff;margin:0 0 10px 0;font-size:20px;}"
                + "p{color:#93a3b5;font-size:14px;line-height:1.45;word-break:break-all;}"
                + ".actions{display:flex;gap:12px;justify-content:center;margin-top:18px;flex-wrap:wrap;}"
                + "button{background:#56dcff22;color:#c9f5ff;border:1px solid #56dcff88;"
                + "border-radius:10px;padding:10px 16px;font-size:14px;font-weight:bold;cursor:pointer;}"
                + "button:focus-visible{outline:2px solid #56dcff;outline-offset:2px;}"
                + "</style></head><body><div class='card'>"
                + "<h2>Servidor indisponível</h2>"
                + "<p>Não foi possível conectar em:<br><strong>" + safeUrl + "</strong></p>"
                + "<p>" + safeReason + "</p>"
                + "<div class='actions'>"
                + "<button onclick='window.AndroidBridge.reloadApp()'>Tentar novamente</button>"
                + "<button onclick='window.AndroidBridge.openServerMenu()'>Trocar servidor</button>"
                + "</div></div></body></html>";
        webView.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
    }

    private static String escapeHtml(String value) {
        if (value == null) {
            return "";
        }
        return value
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#39;");
    }

    private class DeskWebViewClient extends WebViewClient {
        @Override
        public void onReceivedSslError(
                WebView view,
                SslErrorHandler handler,
                SslError error
        ) {
            String errorUrl = error != null ? error.getUrl() : null;
            String host = errorUrl != null ? Uri.parse(errorUrl).getHost() : null;
            // Aceita certificado autoassinado APENAS em hosts locais/privados da LAN.
            if (isPrivateOrLocalHost(host)) {
                handler.proceed();
            } else {
                handler.cancel();
            }
        }

        @Override
        public void onReceivedError(
                WebView view,
                WebResourceRequest request,
                WebResourceError error
        ) {
            if (request == null || !request.isForMainFrame()) {
                return;
            }
            String failingUrl = request.getUrl() != null ? request.getUrl().toString() : currentUrl;
            if (DEFAULT_USB_URL.equals(currentUrl) && !fallbackAttempted) {
                fallbackAttempted = true;
                loadServerUrl(DEFAULT_WIFI_URL);
                return;
            }
            CharSequence desc = error != null ? error.getDescription() : null;
            renderOfflineErrorPage(failingUrl, desc != null ? desc.toString() : null);
        }
    }

    private class DeskWebChromeClient extends WebChromeClient {
        @Override
        public void onPermissionRequest(PermissionRequest request) {
            if (request == null) {
                return;
            }
            Uri origin = request.getOrigin();
            String host = origin != null ? origin.getHost() : null;
            if (!isPrivateOrLocalHost(host)) {
                request.deny();
                return;
            }

            boolean wantsAudio = false;
            String[] resources = request.getResources();
            if (resources != null) {
                for (String res : resources) {
                    if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(res)) {
                        wantsAudio = true;
                        break;
                    }
                }
            }
            if (!wantsAudio) {
                request.deny();
                return;
            }

            mainHandler.post(() -> {
                if (hasAudioPermission()) {
                    request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
                } else {
                    if (pendingPermissionRequest != null) {
                        pendingPermissionRequest.deny();
                    }
                    pendingPermissionRequest = request;
                    requestAudioPermissionIfNeeded();
                }
            });
        }
    }

    /**
     * Ponte JavaScript exposta em `window.AndroidBridge` para integração nativa no RG406H.
     */
    public class AndroidBridge {
        @JavascriptInterface
        public boolean isNativeApp() {
            return true;
        }

        @JavascriptInterface
        @SuppressWarnings("deprecation")
        public void vibrate(int ms) {
            int clampedMs = Math.max(1, Math.min(ms, 2000));
            Vibrator vibrator = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (vibrator != null && vibrator.hasVibrator()) {
                vibrator.vibrate(
                        VibrationEffect.createOneShot(clampedMs, VibrationEffect.DEFAULT_AMPLITUDE)
                );
            }
        }

        @JavascriptInterface
        public String getServerUrl() {
            return currentUrl;
        }

        @JavascriptInterface
        public void setServerUrl(String url) {
            mainHandler.post(() -> saveAndLoadServerUrl(url));
        }

        @JavascriptInterface
        public void reloadApp() {
            mainHandler.post(() -> {
                fallbackAttempted = false;
                loadServerUrl(currentUrl);
            });
        }

        @JavascriptInterface
        public void openServerMenu() {
            MainActivity.this.openServerMenu();
        }
    }
}
