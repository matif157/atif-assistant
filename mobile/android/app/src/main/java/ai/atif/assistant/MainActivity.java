package ai.atif.assistant;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

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
    private Thread recordThread;
    private volatile boolean recording;

    /** False once the server reports no offline speech stack; refreshed on boot. */
    private volatile boolean sttAvailable;

    private static final String SERVER_URL = "http://127.0.0.1:8770/";
    private static final int STT_RATE = 16000; // whisper expects 16 kHz mono PCM16
    private static final int STT_MAX_MS = 8000;
    private static final int STT_MIN_MS = 400;

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
        // llama-server / whisper-cli ship as JNI libs (jniLibs/<abi>/lib*.so)
        // so the installer extracts them into nativeLibraryDir, which is one
        // of the few app-owned locations Android still allows execve() from.
        // Writing them into filesDir instead would hit the API 29+ W^X block
        // (Permission denied from the app, even though run-as can exec it).
        final String dataDir = getFilesDir().getAbsolutePath();
        final String llamaBin = resolveNativeLib("libllama-server.so");
        final String whisperBin = resolveNativeLib("libwhisper-cli.so");
        new Thread(() -> {
            try {
                Python.getInstance().getModule("run_server")
                        .callAttr("start", dataDir, llamaBin, whisperBin);
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
            probeOfflineStt();
            web.post(() -> web.loadUrl(SERVER_URL));
        }).start();
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
     * Absolute path of an extracted JNI lib, or "" when this build/ABI does
     * not ship one. nativeLibraryDir is installer-managed and executable,
     * unlike the app's own files dir.
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
