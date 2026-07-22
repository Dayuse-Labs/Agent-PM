/**
 * Amplitude bootstrap loaded from a static script to keep CSP script-src strict.
 *
 * Creates a buffering proxy so events fired before the SDK loads (e.g. chat_open)
 * are queued and replayed once the real SDK is initialized.
 */
(function bootstrapAmplitude() {
    var _buffer = [];

    function safeString(value, maxLen) {
        return String(value || '').trim().slice(0, maxLen || 128);
    }

    function safeSessionId(value) {
        var parsed = Number(value);
        if (!Number.isFinite(parsed) || parsed <= 0 || !Number.isSafeInteger(parsed)) {
            return undefined;
        }
        return parsed;
    }

    function safeDeviceId(value) {
        var deviceId = safeString(value, 128);
        return /^(null|undefined|none)$/i.test(deviceId) ? '' : deviceId;
    }

    function detectAppPlatform(nativeContext) {
        var explicit = safeString(
            nativeContext && (nativeContext.app_platform || nativeContext.appPlatform
                || nativeContext.platform),
            32
        ).toLowerCase();
        if (explicit === 'ios' || explicit === 'iphone' || explicit === 'ipad') return 'ios';
        if (explicit === 'android') return 'android';

        var userAgent = safeString(window.navigator && window.navigator.userAgent, 512).toLowerCase();
        if (/iphone|ipad|ipod/.test(userAgent)) return 'ios';
        if (/android/.test(userAgent)) return 'android';
        return 'unknown';
    }

    if (!window.amplitude) {
        window.amplitude = {
            init: function () {},
            track: function (event, props) {
                _buffer.push({ event: event, props: props });
            },
            getDeviceId: function () { return ''; },
            getSessionId: function () { return undefined; },
        };
    }

    var amplitudeApiKeyMap = {
        prod: 'ba76a8f0fdbac6f02609480ab477de4f',
        dev: '4490e59977a700c2c1651fde48670583',
    };

    // Match any worldwide prod hostname: www.dayuse.{tld} or ai.dayuse.{tld}.
    // Excludes preprod/staging subdomains and non-dayuse hosts.
    var isProd = /^(www|ai)\.dayuse\.[a-z.]+$/.test(window.location.hostname);
    var amplitudeApiKey = isProd ? amplitudeApiKeyMap.prod : amplitudeApiKeyMap.dev;
    var urlParams = new URLSearchParams(window.location.search);
    var amplitudeDeviceId = '';
    var amplitudeSessionId;

    function resolveAmplitudeContext() {
        var nativeContext = window.__DAYUSE_NATIVE__
            && typeof window.__DAYUSE_NATIVE__ === 'object'
            ? window.__DAYUSE_NATIVE__
            : null;
        var nativeDeviceId = safeDeviceId(nativeContext && nativeContext.amp_device_id);
        var urlDeviceId = safeDeviceId(
            urlParams.get('amplitude_id') || urlParams.get('amp_device_id')
        );
        // The app's native identity must win inside its WebView. Otherwise every
        // chat event is attached to a new browser identity and can never join the
        // native initiated_checkout / purchase events.
        amplitudeDeviceId = nativeDeviceId || urlDeviceId;
        amplitudeSessionId = safeSessionId(
            (nativeContext && nativeContext.amp_session_id)
            || urlParams.get('amp_session_id')
            || urlParams.get('amplitude_session_id')
        );
        var isAppWebView = Boolean(nativeContext)
            || safeString(urlParams.get('source'), 64).toLowerCase() === 'mobile_app';

        // Shared with tracking.js so buffered events and backend breadcrumbs carry
        // the same attribution dimensions even before the SDK finishes loading.
        window.__DAYUSE_AMPLITUDE_CONTEXT__ = Object.freeze({
            deviceId: amplitudeDeviceId,
            sessionId: amplitudeSessionId,
            identitySource: nativeDeviceId ? 'native' : (urlDeviceId ? 'url' : 'sdk_generated'),
            surface: isAppWebView ? 'mobile_app' : 'web',
            appPlatform: isAppWebView ? detectAppPlatform(nativeContext) : null,
        });
        return { nativeDeviceId: nativeDeviceId };
    }

    resolveAmplitudeContext();

    // Some native WebViews inject __DAYUSE_NATIVE__ after the HTML scripts ran.
    // The app entry hook calls this again before emitting its first app-specific
    // event, and native code may call it explicitly after injection as well.
    window.syncDayuseAmplitudeContext = function () {
        var resolved = resolveAmplitudeContext();
        if (resolved.nativeDeviceId
            && window.amplitude && typeof window.amplitude.setDeviceId === 'function') {
            window.amplitude.setDeviceId(amplitudeDeviceId);
        }
        if (amplitudeSessionId
            && window.amplitude && typeof window.amplitude.setSessionId === 'function') {
            window.amplitude.setSessionId(amplitudeSessionId);
        }
        return window.__DAYUSE_AMPLITUDE_CONTEXT__;
    };

    var configureAmplitude = function () {
        if (!window.amplitude || typeof window.amplitude.init !== 'function') {
            return;
        }
        window.amplitude.init(amplitudeApiKey, null, {
            serverUrl: 'https://alitude.dayuse.com/2/httpapi',
            serverZone: 'EU',
            fetchRemoteConfig: true,
            deviceId: amplitudeDeviceId || undefined,
            sessionId: amplitudeSessionId,
            defaultTracking: {
                attribution: true,
                pageViews: false,
                sessions: false,
                formInteractions: false,
                fileDownloads: false,
                elementInteractions: false,
            },
        });

        // Replay buffered events (chat_open, etc.) that fired before SDK loaded
        for (var i = 0; i < _buffer.length; i++) {
            window.amplitude.track(_buffer[i].event, _buffer[i].props);
        }
        _buffer = [];
    };

    var script = document.createElement('script');
    script.src = 'https://cdn.amplitude.com/libs/analytics-browser-2.11.2-min.js.gz';
    script.async = true;
    script.onload = configureAmplitude;
    document.head.appendChild(script);
})();
