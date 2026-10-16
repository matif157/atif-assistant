package ai.atif.assistant;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.ArrayList;
import java.util.Locale;

/**
 * Thin WebView shell around the embedded Python server. The server listens on
 * loopback only; the WebView loads it like any other page, so the whole web
 * front end is reused unchanged. Voice uses the native Android engines through
 * a small JS bridge instead of the Web Speech API, which WebView does not
 * implement.
 */
public class MainActivity extends Activity {

    private WebView web;
    private TextToSpeech tts;
    private SpeechRecognizer recognizer;

    private static final String SERVER_URL = "http://127.0.0.1:8770/";

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
        // llama-server ships as a JNI lib (jniLibs/arm64-v8a/libllama-server.so)
        // so the installer extracts it into nativeLibraryDir, which is one of
        // the few app-owned locations Android still allows execve() from.
        // Writing it into filesDir instead would hit the API 29+ W^X block
        // (Permission denied from the app, even though run-as can exec it).
        final String dataDir = getFilesDir().getAbsolutePath();
        final String llamaBin = resolveLlamaServer();
        new Thread(() -> {
            try {
                Python.getInstance().getModule("run_server").callAttr("start", dataDir, llamaBin);
            } catch (Throwable t) {
                t.printStackTrace();
            }
        }).start();

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient());
        web.addJavascriptInterface(new VoiceBridge(), "AndroidVoice");
        setContentView(web);

        requestAudioPermission();
        tts = new TextToSpeech(this, status -> { /* locale set per utterance */ });

        // First launch boots Python + uvicorn (a couple of seconds). Wait for
        // the port to accept connections before loading, otherwise the WebView
        // would render a connection error and never retry.
        new Thread(() -> {
            if (!waitForServer(20_000)) {
                android.util.Log.w("Atif", "server not ready after 20s, loading anyway");
            }
            web.post(() -> web.loadUrl(SERVER_URL));
        }).start();
    }

    private static boolean waitForServer(long timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress("127.0.0.1", 8770), 250);
                return true;
            } catch (Exception e) {
                try {
                    Thread.sleep(200);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return false;
                }
            }
        }
        return false;
    }

    /**
     * Absolute path of the extracted llama-server JNI lib, or "" when this
     * build/ABI does not ship one. nativeLibraryDir is installer-managed and
     * executable, unlike the app's own files dir.
     */
    private String resolveLlamaServer() {
        File lib = new File(getApplicationInfo().nativeLibraryDir, "libllama-server.so");
        if (!lib.isFile()) {
            android.util.Log.w("Atif", "no llama-server lib at " + lib.getAbsolutePath());
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
            runOnUiThread(() -> {
                if (recognizer != null) {
                    recognizer.destroy();
                    recognizer = null;
                }
            });
        }
    }

    private void startListening(String lang) {
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
