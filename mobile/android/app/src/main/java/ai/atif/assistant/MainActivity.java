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

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }
        final String dataDir = getFilesDir().getAbsolutePath();
        new Thread(() -> {
            try {
                Python.getInstance().getModule("run_server").callAttr("start", dataDir);
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

        web.loadUrl("http://127.0.0.1:8770/");
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
