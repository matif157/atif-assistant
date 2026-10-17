package ai.atif.assistant;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.SystemClock;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.TextView;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;

/**
 * Thin WebView shell around the embedded Python server. The server listens on
 * loopback only; the WebView loads it like any other page, so the whole web
 * front end is reused unchanged. Voice uses the native Android engines through
 * a small JS bridge instead of the Web Speech API, which WebView does not
 * implement.
 *
 * Boot UX: a dark splash with live status while the engine starts; a timeout
 * or a Python failure lands on an error screen with RETRY and COPY
 * DIAGNOSTICS instead of a dead WebView error page.
 */
public class MainActivity extends Activity {

    private WebView web;
    private TextToSpeech tts;
    private SpeechRecognizer recognizer;
    private Thread recordThread;
    private volatile boolean recording;

    /** False once the server reports no offline speech stack; refreshed on boot. */
    private volatile boolean sttAvailable;

    // Boot UI
    private View bootSplash;
    private View bootErrorView;
    private TextView bootStatus;
    private TextView bootErrorDetail;
    private volatile String bootError;
    /** Set by the server thread when start() throws; the wait loop reads it. */
    private volatile String bootPyErr;
    private volatile boolean pageLoaded;
    /** Bumped on every RETRY so stale boot threads stop touching the UI. */
    private volatile int bootGen;
    /** Silent post-load restarts used this boot (capped at 3). */
    private int serverRestarts;
    private String lastLlamaBin = "";
    private String lastWhisperBin = "";

    // App lock (opt-in fingerprint gate; off unless enabled at onboarding)
    private View lockView;
    private TextView lockHint;
    private android.hardware.biometrics.BiometricPrompt lockPrompt;
    private CancellationSignal lockCancel;
    private volatile boolean lockShowing;
    /** elapsedRealtime when the activity last stopped; 0 = never backgrounded. */
    private long stoppedAt;

    private static final String SERVER_URL = "http://127.0.0.1:8770/";
    private static final int STT_RATE = 16000; // whisper expects 16 kHz mono PCM16
    private static final int STT_MAX_MS = 8000;
    private static final int STT_MIN_MS = 400;
    private static final long BOOT_TIMEOUT_MS = 25_000;

    /**
     * targetSdk 35+ is edge-to-edge: content draws behind the status and
     * navigation bars unless the insets are consumed here. Pad the root view
     * with the system-bar insets (IME included, so adjustResize-style keyboard
     * lift keeps working) and force *light* icons off: the theme is Material
     * Light but every screen is dark, so dark icons would be invisible on the
     * transparent bars.
     */
    private void applyEdgeToEdge() {
        final View root = findViewById(android.R.id.content);
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            root.setOnApplyWindowInsetsListener((v, insets) -> {
                android.graphics.Insets bars = insets.getInsets(
                        android.view.WindowInsets.Type.systemBars()
                                | android.view.WindowInsets.Type.ime());
                v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
                return insets;
            });
            android.view.WindowInsetsController c =
                    getWindow().getInsetsController();
            if (c != null) {
                c.setSystemBarsAppearance(
                        0,
                        android.view.WindowInsetsController
                                .APPEARANCE_LIGHT_STATUS_BARS
                                | android.view.WindowInsetsController
                                .APPEARANCE_LIGHT_NAVIGATION_BARS);
            }
        } else {
            // API 24-29: same contract via the legacy layout flags (the
            // enforcement itself only exists on API 35+, but opting out
            // manually keeps behaviour identical across versions).
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
            root.setOnApplyWindowInsetsListener((v, insets) -> {
                v.setPadding(
                        insets.getSystemWindowInsetLeft(),
                        insets.getSystemWindowInsetTop(),
                        insets.getSystemWindowInsetRight(),
                        insets.getSystemWindowInsetBottom());
                return insets;
            });
            getWindow().getDecorView().setSystemUiVisibility(
                    getWindow().getDecorView().getSystemUiVisibility()
                            & ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
                            & ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        }
        // No-op on 35+ (bars are forced transparent there); keeps 24-34
        // matching the app background instead of the theme's light colour.
        getWindow().setStatusBarColor(0xFF0B0E14);
        getWindow().setNavigationBarColor(0xFF0B0E14);
    }

    /**
     * Raises the foreground service so the embedded engine (and its loopback
     * server) survives backgrounding instead of being frozen within minutes.
     */
    private void startEngineService() {
        try {
            Intent svc = new Intent(this, EngineService.class);
            if (Build.VERSION.SDK_INT >= 26) {
                startForegroundService(svc);
            } else {
                startService(svc);
            }
        } catch (Throwable t) {
            android.util.Log.w("Atif", "engine service not started", t);
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }
        // Debug builds only: chrome://inspect can attach to the WebView.
        if ((getApplicationInfo().flags
                & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }

        setContentView(R.layout.activity_main);
        applyEdgeToEdge();
        startEngineService();
        // Phase 6: reminder notifications need the runtime grant on 13+.
        // Asking once at launch is deliberate - the engine polls reminders
        // from the first minute and a denied permission would drop them.
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                        != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1010);
        }
        bootSplash = findViewById(R.id.boot_splash);
        bootErrorView = findViewById(R.id.boot_error);
        bootStatus = findViewById(R.id.boot_status);
        bootErrorDetail = findViewById(R.id.boot_error_detail);
        lockView = findViewById(R.id.lock_screen);
        lockHint = findViewById(R.id.lock_hint);

        web = findViewById(R.id.web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        // Dark under the first paint: matches the splash and the page, so no
        // white flash between "interface loaded" and the CSS landing.
        web.setBackgroundColor(0xFF0B0E14);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(
                    WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                boolean local = "http".equals(uri.getScheme())
                        && "127.0.0.1".equals(uri.getHost())
                        && uri.getPort() == 8770;
                if (local) {
                    return false; // our own pages load in place
                }
                // Anything else (links in documents, pasted URLs...) leaves
                // the WebView: an external site must never run against the
                // AndroidVoice bridge, which can start the microphone.
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Throwable t) {
                    android.util.Log.w("Atif", "no handler for " + uri);
                }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                pageLoaded = true;
                if (bootSplash != null) {
                    bootSplash.setVisibility(View.GONE);
                }
            }

            @Override
            public void onReceivedError(
                    WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && !pageLoaded) {
                    showBootError("The interface failed to load: "
                            + error.getDescription());
                }
            }
        });
        web.addJavascriptInterface(new VoiceBridge(), "AndroidVoice");

        Button retryBtn = findViewById(R.id.boot_retry);
        Button copyBtn = findViewById(R.id.boot_copy);
        retryBtn.setOnClickListener(v -> startBoot());
        copyBtn.setOnClickListener(v -> {
            String report = collectDiagnostics();
            try {
                ClipboardManager cm =
                        (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
                if (cm != null) {
                    cm.setPrimaryClip(ClipData.newPlainText("Atif diagnostics", report));
                    if (bootErrorDetail != null) {
                        bootErrorDetail.setText(
                                "Diagnostics copied to clipboard - paste them anywhere.");
                    }
                }
            } catch (Throwable t) {
                android.util.Log.w("Atif", "clipboard failed: " + t);
            }
        });

        Button lockBtn = findViewById(R.id.lock_unlock);
        lockBtn.setOnClickListener(v -> startBiometric());

        requestAudioPermission();
        tts = new TextToSpeech(this, status -> { /* locale set per utterance */ });

        // First launch boots Python + uvicorn (a couple of seconds). The
        // splash shows live status; on timeout or failure the error screen
        // appears - the WebView never renders a dead connection page.
        startBoot();

        // Boot runs behind the lock (the engine is local, nothing is shown);
        // the gate only decides when the UI becomes visible.
        if (appLockEnabled()) {
            showLock(false);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Cold start is already covered by onCreate; re-prompt only when the
        // app comes back from the background long enough to re-lock.
        if (appLockEnabled() && stoppedAt > 0
                && (SystemClock.elapsedRealtime() - stoppedAt) > 8000) {
            showLock(true);
        }
    }

    @Override
    protected void onStop() {
        stoppedAt = SystemClock.elapsedRealtime();
        super.onStop();
    }

    // --- app lock ------------------------------------------------------------

    private SharedPreferences lockPrefs() {
        return getSharedPreferences("atif_lock", MODE_PRIVATE);
    }

    private boolean appLockEnabled() {
        return lockPrefs().getBoolean("app_lock", false);
    }

    /** Hardware we can actually prompt for (fingerprint / strong biometric). */
    private boolean hasLockHardware() {
        if (Build.VERSION.SDK_INT < 28) {
            return false; // framework BiometricPrompt needs Android 9
        }
        PackageManager pm = getPackageManager();
        if (Build.VERSION.SDK_INT >= 29) {
            // "android.hardware.biometric_strong" (PackageManager's constant
            // name for it is not in every platform SDK).
            return pm.hasSystemFeature("android.hardware.biometric_strong")
                    || pm.hasSystemFeature(PackageManager.FEATURE_FINGERPRINT);
        }
        return pm.hasSystemFeature(PackageManager.FEATURE_FINGERPRINT);
    }

    /**
     * Show the lock gate (or re-prompt). Never bricks: when the device has
     * nothing to authenticate with, or the prompt itself fails, the app
     * unlocks honestly instead of locking the user out forever.
     */
    private void showLock(boolean rePrompt) {
        if (lockShowing && !rePrompt) {
            return;
        }
        if (lockView == null || !hasLockHardware()) {
            unlock();
            return;
        }
        lockShowing = true;
        lockView.setVisibility(View.VISIBLE);
        if (lockHint != null) {
            lockHint.setText(
                    "Unlock with your fingerprint to open Atif Assistant.");
        }
        startBiometric();
    }

    private void startBiometric() {
        if (Build.VERSION.SDK_INT < 28 || lockView == null) {
            unlock();
            return;
        }
        try {
            cancelPrompt();
            java.util.concurrent.Executor exec = getMainExecutor();
            lockPrompt = new android.hardware.biometrics.BiometricPrompt.Builder(this)
                    .setTitle("Atif Assistant")
                    .setSubtitle("Confirm it's you to open the app")
                    .setNegativeButton("Cancel", exec, (btn, tag) -> {
                        // Stay on the lock screen; UNLOCK re-prompts.
                        showLockHint("Locked. Tap UNLOCK and try again.");
                    })
                    .build();
            lockCancel = new CancellationSignal();
            lockPrompt.authenticate(makeCrypto(), lockCancel, exec,
                    new android.hardware.biometrics.BiometricPrompt
                            .AuthenticationCallback() {
                        @Override
                        public void onAuthenticationSucceeded(
                                android.hardware.biometrics.BiometricPrompt
                                        .AuthenticationResult result) {
                            unlock();
                        }

                        @Override
                        public void onAuthenticationError(int code, CharSequence msg) {
                            if (code == 1 /* HW_UNAVAILABLE */
                                    || code == 11 /* NO_BIOMETRICS */
                                    || code == 14 /* NO_DEVICE_CREDENTIAL */) {
                                // Nothing usable to verify identity with -
                                // skip the gate rather than brick the app.
                                unlock();
                            } else {
                                showLockHint("Locked. Tap UNLOCK and try again.");
                            }
                        }

                        @Override
                        public void onAuthenticationFailed() {
                            // Wrong finger; the system prompt offers retries.
                        }
                    });
        } catch (Throwable t) {
            // Prompt infrastructure broken on this device: availability wins
            // over the lock - never leave the user staring at a dead gate.
            android.util.Log.w("Atif", "biometric prompt failed: " + t);
            unlock();
        }
    }

    /**
     * A throwaway AndroidKeyStore AES key purely to satisfy the prompt's
     * CryptoObject requirement; it protects nothing and gates nothing.
     */
    private android.hardware.biometrics.BiometricPrompt.CryptoObject makeCrypto() {
        try {
            KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
            ks.load(null);
            if (!ks.containsAlias("atif_applock")) {
                KeyGenerator gen = KeyGenerator.getInstance(
                        KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
                gen.init(new KeyGenParameterSpec.Builder("atif_applock",
                        KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_CBC)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_PKCS7)
                        .setUserAuthenticationRequired(false)
                        .build());
                gen.generateKey();
            }
            Cipher cipher = Cipher.getInstance("AES/CBC/PKCS7Padding");
            cipher.init(Cipher.ENCRYPT_MODE, ks.getKey("atif_applock", null));
            return new android.hardware.biometrics.BiometricPrompt.CryptoObject(cipher);
        } catch (Throwable t) {
            return null; // modern releases accept a null-crypto prompt
        }
    }

    private void showLockHint(final String text) {
        runOnUiThread(() -> {
            if (lockView != null && lockShowing && lockHint != null) {
                lockHint.setText(text);
            }
        });
    }

    private void unlock() {
        cancelPrompt();
        lockShowing = false;
        runOnUiThread(() -> {
            if (lockView != null) {
                lockView.setVisibility(View.GONE);
            }
        });
    }

    private void cancelPrompt() {
        try {
            if (lockCancel != null) {
                lockCancel.cancel();
            }
        } catch (Throwable ignored) { /* already gone */ }
        lockCancel = null;
    }

    /**
     * (Re)start the embedded server and run the splash -> page sequence.
     * A RETRY calls this again: run_server clears its started guard after a
     * failure, and stale boot threads from earlier attempts stop themselves
     * through the generation counter.
     */
    private void startBoot() {
        final int gen = ++bootGen;
        bootError = null;
        bootPyErr = null;
        serverRestarts = 0;
        pageLoaded = false;
        if (bootSplash != null) {
            bootSplash.setVisibility(View.VISIBLE);
        }
        if (bootErrorView != null) {
            bootErrorView.setVisibility(View.GONE);
        }
        if (web != null) {
            web.setVisibility(View.INVISIBLE);
        }
        setBootStatus("Starting the offline engine...");

        // llama-server / whisper-cli ship as JNI libs (jniLibs/<abi>/lib*.so)
        // so the installer extracts them into nativeLibraryDir, which is one
        // of the few app-owned locations Android still allows execve() from.
        // Writing them into filesDir instead would hit the API 29+ W^X block
        // (Permission denied from the app, even though run-as can exec it).
        lastLlamaBin = resolveNativeLib("libllama-server.so");
        lastWhisperBin = resolveNativeLib("libwhisper-cli.so");
        startPythonServer(gen);

        new Thread(() -> {
            setBootStatus("Waiting for the offline engine...");
            long deadline = System.currentTimeMillis() + BOOT_TIMEOUT_MS;
            boolean up = false;
            while (System.currentTimeMillis() < deadline && gen == bootGen) {
                if (bootPyErr != null) {
                    return; // error screen already shown by the server thread
                }
                if (portOpen()) {
                    up = true;
                    break;
                }
                try {
                    Thread.sleep(250);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
            if (gen != bootGen) {
                return; // a RETRY superseded this attempt
            }
            if (!up) {
                String reason = bootPyErr != null
                        ? "The offline engine failed to start.\n" + bootPyErr
                        : "The offline engine did not respond within "
                                + (BOOT_TIMEOUT_MS / 1000)
                                + " seconds. It may still be busy, or the device "
                                + "may be low on storage.";
                showBootError(reason);
                return;
            }
            setBootStatus("Loading interface...");
            probeOfflineStt();
            if (gen != bootGen) {
                return;
            }
            web.post(() -> {
                if (gen != bootGen) {
                    return;
                }
                web.setVisibility(View.VISIBLE);
                web.loadUrl(SERVER_URL);
                // Never a silent dark screen: if the first page takes long,
                // the status line says so instead of freezing.
                bootStatus.postDelayed(() -> {
                    if (gen == bootGen && !pageLoaded && bootError == null) {
                        setBootStatus("Loading interface... (still working)");
                    }
                }, 8000);
            });
        }, "boot-wait").start();
    }

    /**
     * Spawn the Python server thread. Before the page has loaded, a crash is
     * the boot error screen; after it, the app silently restarts the server
     * (up to 3 times) so a wedged uvicorn does not brick an open session -
     * the web UI's health poll turns the status dot back on when it returns.
     */
    private void startPythonServer(final int gen) {
        final String dataDir = getFilesDir().getAbsolutePath();
        final String llamaBin = lastLlamaBin;
        final String whisperBin = lastWhisperBin;
        Thread server = new Thread(() -> {
            try {
                Python.getInstance().getModule("run_server")
                        .callAttr("start", dataDir, llamaBin, whisperBin);
            } catch (Throwable t) {
                String msg = t.getClass().getSimpleName() + ": " + t.getMessage();
                bootPyErr = msg;
                android.util.Log.e("Atif", "server thread failed: " + msg, t);
                if (gen != bootGen) {
                    return; // superseded by a RETRY
                }
                if (pageLoaded) {
                    scheduleServerRestart(gen, msg);
                } else {
                    showBootError("The offline engine failed to start.\n" + msg);
                }
            }
        }, "python-server");
        server.setDaemon(true);
        server.start();
    }

    /** Restart the engine in the background after a post-load crash. */
    private void scheduleServerRestart(final int gen, final String why) {
        serverRestarts++;
        if (serverRestarts > 3 || gen != bootGen) {
            if (gen == bootGen) {
                showBootError("The offline engine stopped and could not be "
                        + "restarted after 3 attempts.\n" + why);
            }
            return;
        }
        android.util.Log.w("Atif", "server died (" + why + "), restart "
                + serverRestarts + " of 3");
        new Thread(() -> {
            try {
                Thread.sleep(2000);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
            if (gen == bootGen) {
                startPythonServer(gen);
            }
        }, "server-restart").start();
    }

    /** Update the splash status line; safe from any thread. */
    private void setBootStatus(final String text) {
        if (bootStatus == null) {
            return;
        }
        bootStatus.post(() -> bootStatus.setText(text));
    }

    /** Leave the splash for the error screen with an honest explanation. */
    private void showBootError(final String detail) {
        bootError = detail;
        runOnUiThread(() -> {
            if (bootSplash != null) {
                bootSplash.setVisibility(View.GONE);
            }
            if (bootErrorView != null) {
                bootErrorView.setVisibility(View.VISIBLE);
            }
            if (bootErrorDetail != null) {
                bootErrorDetail.setText(detail
                        + "\n\nTap RETRY to try again, or copy the diagnostics "
                        + "and share them when asking for help.");
            }
        });
    }

    private static boolean portOpen() {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress("127.0.0.1", 8770), 250);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** Everything worth pasting into a bug report; never throws. */
    private String collectDiagnostics() {
        StringBuilder sb = new StringBuilder("Atif Assistant diagnostics\n");
        try {
            sb.append("time: ").append(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                    .format(new Date())).append('\n');
        } catch (Throwable ignored) { /* absurd clock */ }
        sb.append("device: ").append(Build.MANUFACTURER).append(' ').append(Build.MODEL)
                .append(", Android ").append(Build.VERSION.RELEASE)
                .append(" (SDK ").append(Build.VERSION.SDK_INT).append(")\n");
        try {
            android.content.pm.PackageInfo pi =
                    getPackageManager().getPackageInfo(getPackageName(), 0);
            sb.append("version: ").append(pi.versionName).append('\n');
        } catch (Throwable ignored) { /* package manager hiccups */ }
        try {
            long free = getFilesDir().getUsableSpace();
            sb.append("storage free: ").append(free / 1048576).append(" MB\n");
        } catch (Throwable ignored) { /* ignore */ }
        sb.append("llama-server: ")
                .append(lastLlamaBin == null || lastLlamaBin.isEmpty() ? "missing" : "present")
                .append('\n');
        sb.append("whisper-cli: ")
                .append(lastWhisperBin == null || lastWhisperBin.isEmpty() ? "missing" : "present")
                .append('\n');
        sb.append("boot error: ")
                .append(bootError == null ? "unknown" : bootError)
                .append('\n');
        sb.append("\n--- logcat (this app) ---\n").append(logcatTail());
        return sb.toString();
    }

    /** Last few hundred of our own app's logcat lines; never throws. */
    private String logcatTail() {
        Process p = null;
        try {
            p = new ProcessBuilder(
                    "logcat", "-d", "-t", "400",
                    "--pid=" + android.os.Process.myPid())
                    .redirectErrorStream(true)
                    .start();
            ByteArrayOutputStream buf = new ByteArrayOutputStream(16384);
            InputStream in = p.getInputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = in.read(chunk)) > 0) {
                buf.write(chunk, 0, n);
            }
            in.close();
            String all = buf.toString(StandardCharsets.UTF_8.name());
            if (all.length() > 8000) {
                all = all.substring(all.length() - 8000);
            }
            return all.isEmpty() ? "(no logcat output)" : all;
        } catch (Throwable t) {
            return "(logcat unavailable: " + t + ")";
        } finally {
            if (p != null) {
                p.destroy();
            }
        }
    }

    /** Cache whether the server has whisper + a model, so listen() can choose. */
    private void probeOfflineStt() {
        try {
            URL url = new URL(SERVER_URL + "api/speech");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(2000);
            conn.setReadTimeout(2000);
            InputStream in = conn.getInputStream();
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = in.read(chunk)) > 0) {
                buf.write(chunk, 0, n);
            }
            in.close();
            conn.disconnect();
            JSONObject root = new JSONObject(buf.toString(StandardCharsets.UTF_8.name()));
            sttAvailable = root.optJSONObject("stt").optBoolean("available", false);
        } catch (Throwable t) {
            sttAvailable = false;
        }
    }

    /**
     * Absolute path of an extracted JNI lib, or "" when this build/ABI does
     * not ship one. nativeLibraryDir is installer-managed and executable,
     * unlike the app's own files dir: writing the libs into filesDir instead
     * would hit the API 29+ W^X block (Permission denied from the app, even
     * though run-as can exec it).
     */
    private String resolveNativeLib(String libName) {
        File lib = new File(getApplicationInfo().nativeLibraryDir, libName);
        if (!lib.isFile()) {
            android.util.Log.w("Atif", "no native lib at " + lib.getAbsolutePath());
            return "";
        }
        if (!lib.setExecutable(true, false)) {
            android.util.Log.w("Atif", "could not chmod +x " + lib.getAbsolutePath());
        }
        return lib.getAbsolutePath();
    }

    private void requestAudioPermission() {
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
        }
    }

    private class VoiceBridge {
        @JavascriptInterface
        public boolean available() {
            return true;
        }

        @JavascriptInterface
        public void speak(String text, String lang) {
            if (tts == null || text == null) {
                return;
            }
            tts.setLanguage(Locale.forLanguageTag(lang == null ? "en" : lang));
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "atif");
        }

        @JavascriptInterface
        public void listen(String lang) {
            runOnUiThread(() -> startListening(lang));
        }

        /** Silence TTS and cancel any active recognition (end call / hands-free off). */
        @JavascriptInterface
        public void stop() {
            if (tts != null) {
                tts.stop();
            }
            recording = false;
            runOnUiThread(() -> {
                if (recognizer != null) {
                    recognizer.destroy();
                    recognizer = null;
                }
            });
        }

        /** True when this device can show a fingerprint gate (Android 9+). */
        @JavascriptInterface
        public boolean appLockAvailable() {
            return hasLockHardware();
        }

        @JavascriptInterface
        public boolean appLockEnabled() {
            return MainActivity.this.appLockEnabled();
        }

        @JavascriptInterface
        public void setAppLock(boolean on) {
            lockPrefs().edit().putBoolean("app_lock", on).apply();
        }

        /** Light tap feedback for send / STOP / feedback buttons. Runs on the
         *  view haptic path, which needs no VIBRATE permission. */
        @JavascriptInterface
        public void haptic() {
            runOnUiThread(() -> {
                View v = getWindow().getDecorView();
                v.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK);
            });
        }

        /** Foreground notification for a due reminder (Phase 6). Named
         *  showNotification because Object.notify is final. Dropped, not
         *  queued, when the user has not granted POST_NOTIFICATIONS. */
        @JavascriptInterface
        public void showNotification(String title, String body) {
            if (Build.VERSION.SDK_INT >= 33
                    && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                            != PackageManager.PERMISSION_GRANTED) {
                return;
            }
            NotificationManager nm =
                    (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm == null) {
                return;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                nm.createNotificationChannel(new NotificationChannel(
                        "reminders", "Reminders", NotificationManager.IMPORTANCE_DEFAULT));
            }
            Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                    ? new Notification.Builder(MainActivity.this, "reminders")
                    : new Notification.Builder(MainActivity.this);
            Notification n = b
                    .setContentTitle(title == null ? "Atif Assistant" : title)
                    .setContentText(body == null ? "" : body)
                    .setSmallIcon(R.mipmap.ic_launcher)
                    .setAutoCancel(true)
                    .build();
            nm.notify((int) SystemClock.uptimeMillis(), n);
        }

        /** Phase 8: has the user granted notification access (the official
         *  way an app may read other apps' notifications)? */
        @JavascriptInterface
        public boolean notificationAccess() {
            try {
                String enabled = android.provider.Settings.Secure.getString(
                        getContentResolver(), "enabled_notification_listeners");
                String pkg = getPackageName();
                if (enabled == null || pkg == null) {
                    return false;
                }
                for (String part : enabled.split(":")) {
                    if (pkg.equals(part.split("/")[0])) {
                        return true;
                    }
                }
            } catch (Throwable t) {
                android.util.Log.w("Atif", "listener state check failed", t);
            }
            return false;
        }

        /** Opens the system screen where notification access is granted -
         *  the OS owns that flow; we can never self-grant it. */
        @JavascriptInterface
        public void openNotificationAccess() {
            try {
                startActivity(new Intent(
                        android.provider.Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS));
            } catch (Throwable t) {
                try {
                    startActivity(new Intent(
                            "android.settings.ACTION_NOTIFICATION_ACCESS_SETTINGS"));
                } catch (Throwable t2) {
                    android.util.Log.w("Atif", "no notification access screen", t2);
                }
            }
        }
    }

    /**
     * Offline-first: record with AudioRecord and let whisper transcribe on the
     * server when the stack is installed; otherwise fall back to the platform
     * recogniser (which needs a network, but keeps the mic working).
     */
    private void startListening(String lang) {
        if (sttAvailable) {
            whisperListen(lang);
        } else {
            startListeningLegacy(lang);
        }
    }

    private void whisperListen(final String lang) {
        if (recording) {
            return; // already capturing; the next result will arrive on its own
        }
        new Thread(() -> {
            byte[] wav = recordWav();
            if (wav == null) {
                emitResult("");
                return;
            }
            String text = postTranscribe(wav, lang);
            if (text == null) {
                // Stack vanished (model deleted, server restarted...): one
                // fallback so the mic is never simply dead.
                sttAvailable = false;
                startListeningLegacy(lang);
                return;
            }
            emitResult(text);
        }, "whisper-stt").start();
    }

    /** Capture 16 kHz mono PCM16 with a simple energy VAD; null on failure. */
    private byte[] recordWav() {
        int minBuf = AudioRecord.getMinBufferSize(
                STT_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord ar;
        try {
            ar = new AudioRecord(
                    MediaRecorder.AudioSource.MIC, STT_RATE,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(minBuf, 3200) * 4);
        } catch (Throwable t) {
            return null;
        }
        if (ar.getState() != AudioRecord.STATE_INITIALIZED) {
            ar.release();
            return null;
        }
        ByteArrayOutputStream pcm = new ByteArrayOutputStream(STT_RATE * 2 * 9);
        byte[] frame = new byte[3200]; // 100 ms
        final int threshold = 600;     // of 32767; quiet-room noise sits well below
        int speechMs = 0;
        int silenceMs = 0;
        recording = true;
        try {
            ar.startRecording();
            while (recording && speechMs + silenceMs < STT_MAX_MS) {
                int got = ar.read(frame, 0, frame.length);
                if (got <= 0) {
                    break;
                }
                int peak = 0;
                for (int i = 0; i + 1 < got; i += 2) {
                    int s = (frame[i] & 0xff) | (frame[i + 1] << 8);
                    int a = s < 0 ? -s : s;
                    if (a > peak) {
                        peak = a;
                    }
                }
                pcm.write(frame, 0, got);
                int ms = got * 1000 / (STT_RATE * 2);
                if (peak >= threshold) {
                    speechMs += ms;
                    silenceMs = 0;
                } else if (speechMs > 0) {
                    silenceMs += ms;
                    if (silenceMs >= 400) {
                        break; // pause after speech: the utterance is over
                    }
                }
            }
        } catch (Throwable t) {
            return null;
        } finally {
            recording = false;
            try {
                ar.stop();
            } catch (Throwable ignored) { /* already stopped */ }
            ar.release();
        }
        if (speechMs < STT_MIN_MS) {
            return null; // never spoke (or only noise)
        }
        return wavBytes(pcm.toByteArray());
    }

    /** Wrap raw PCM16 mono @16 kHz in a canonical 44-byte WAV header. */
    private static byte[] wavBytes(byte[] pcm) {
        int dataLen = pcm.length;
        byte[] wav = new byte[44 + dataLen];
        java.nio.ByteBuffer b = java.nio.ByteBuffer.wrap(wav);
        b.put("RIFF".getBytes(StandardCharsets.US_ASCII));
        b.putInt(36 + dataLen);
        b.put("WAVE".getBytes(StandardCharsets.US_ASCII));
        b.put("fmt ".getBytes(StandardCharsets.US_ASCII));
        b.putInt(16);
        b.putShort((short) 1); // PCM
        b.putShort((short) 1); // mono
        b.putInt(STT_RATE);
        b.putInt(STT_RATE * 2); // byte rate
        b.putShort((short) 2);  // block align
        b.putShort((short) 16); // bits
        b.put("data".getBytes(StandardCharsets.US_ASCII));
        b.putInt(dataLen);
        b.put(pcm);
        return wav;
    }

    /** POST the clip to /api/stt; null means "server cannot transcribe". */
    private String postTranscribe(byte[] wav, String lang) {
        HttpURLConnection conn = null;
        try {
            JSONObject body = new JSONObject();
            body.put("audio", Base64.encodeToString(wav, Base64.NO_WRAP));
            body.put("lang", lang == null ? "auto" : lang);
            byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
            conn = (HttpURLConnection) new URL(SERVER_URL + "api/stt").openConnection();
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(150_000); // small model on a phone: up to ~2 min cold
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setFixedLengthStreamingMode(payload.length);
            conn.getOutputStream().write(payload);
            int code = conn.getResponseCode();
            InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            if (in == null) {
                return null;
            }
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = in.read(chunk)) > 0) {
                buf.write(chunk, 0, n);
            }
            in.close();
            if (code != 200) {
                return null;
            }
            return new JSONObject(buf.toString(StandardCharsets.UTF_8.name()))
                    .optString("text", "");
        } catch (Throwable t) {
            return null;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    /** The platform recogniser: online, but always available as a fallback. */
    private void startListeningLegacy(String lang) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            emitResult("");
            return;
        }
        if (recognizer != null) {
            recognizer.destroy();
        }
        recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override
            public void onResults(Bundle results) {
                ArrayList<String> list =
                        results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                emitResult(list != null && !list.isEmpty() ? list.get(0) : "");
            }

            @Override
            public void onError(int error) {
                emitResult("");
            }

            @Override public void onReadyForSpeech(Bundle params) {}
            @Override public void onBeginningOfSpeech() {}
            @Override public void onRmsChanged(float rmsdB) {}
            @Override public void onBufferReceived(byte[] buffer) {}
            @Override public void onEndOfSpeech() {}
            @Override public void onPartialResults(Bundle partialResults) {}
            @Override public void onEvent(int eventType, Bundle params) {}
        });

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang == null ? "en-US" : lang);
        recognizer.startListening(intent);
    }

    private void emitResult(final String text) {
        final String js = "window.onAndroidSpeechResult && window.onAndroidSpeechResult("
                + jsQuote(text) + ")";
        web.post(() -> web.evaluateJavascript(js, null));
    }

    private static String jsQuote(String s) {
        if (s == null) {
            s = "";
        }
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ") + "\"";
    }

    @Override
    public void onBackPressed() {
        if (lockShowing) {
            // Locked: send the app to the background rather than revealing
            // the UI behind the gate.
            moveTaskToBack(true);
            return;
        }
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (tts != null) {
            tts.stop();
            tts.shutdown();
        }
        if (recognizer != null) {
            recognizer.destroy();
        }
        super.onDestroy();
    }
}
