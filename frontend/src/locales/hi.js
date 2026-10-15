/**
 * Hindi, keyed on the English sentence. See `lib/i18n.js` for why the key is the sentence.
 *
 * **Written the way a rep talks, not the way a dictionary does.** A field rep in an FMCG market
 * says "photo", "GPS", "route", "order" in English in the middle of a Hindi sentence, every day.
 * Translating those into shuddh Hindi - छायाचित्र for photo, मार्ग for route - produces text that
 * is correct and that nobody reads. Where the English word is the word people actually use, it
 * stays, in Devanagari where that reads more naturally.
 *
 * Numbers, currency and dates are deliberately not here. They are formatted by the same code in
 * both languages, because a rupee figure a rep reads aloud to a shopkeeper must not change shape
 * with a language setting.
 */
export default {
  // ---------------------------------------------------------------- starting the day
  "Today's assignment": 'आज का काम',
  'Capture your location': 'अपनी लोकेशन लें',
  'Getting a fix…': 'लोकेशन ली जा रही है…',
  'Tap to try again': 'दोबारा लेने के लिए दबाएँ',
  'Take the start-of-day photo': 'दिन शुरू करने की फ़ोटो लें',
  'Recorded with your day.': 'आपके दिन के साथ दर्ज हो गई।',
  "Today's route": 'आज का रूट',
  'Shops planned': 'तय दुकानें',
  'Route distance': 'रूट की दूरी',
  'Expected time': 'अनुमानित समय',
  'No route planned': 'कोई रूट तय नहीं है',
  'Start day': 'दिन शुरू करें',
  'Starting…': 'शुरू हो रहा है…',
  'Odometer reading': 'ओडोमीटर रीडिंग',
  'e.g. 14250': 'जैसे 14250',
  '(optional)': '(वैकल्पिक)',
  Required: 'ज़रूरी',
  Optional: 'वैकल्पिक',

  // The three sentences that say why the button will not move. Each one names the thing to do,
  // because "cannot start" tells a rep nothing they can act on.
  'Capture your location first.': 'पहले अपनी लोकेशन लें।',
  'Capture your location to continue.': 'आगे बढ़ने के लिए लोकेशन लें।',
  'Take the start-of-day photo first.': 'पहले दिन शुरू करने की फ़ोटो लें।',
  'Take the photo to continue.': 'आगे बढ़ने के लिए फ़ोटो लें।',
  'Could not read that photo. Try taking it again.':
    'यह फ़ोटो पढ़ी नहीं जा सकी। दोबारा लेकर देखें।',
  'Could not start your day. Try again in a moment.':
    'आपका दिन शुरू नहीं हो सका। थोड़ी देर में दोबारा कोशिश करें।',

  // ---------------------------------------------------------------- arriving at a shop
  'Check in': 'चेक इन करें',
  'Checking in…': 'चेक इन हो रहा है…',
  'Take the photo at the shop before you check in.':
    'चेक इन करने से पहले दुकान पर फ़ोटो लें।',
  'Shop photo': 'दुकान की फ़ोटो',
  'You are too far from this shop': 'आप इस दुकान से बहुत दूर हैं',
  'Ask your manager to allow this': 'अपने मैनेजर से इसकी अनुमति लें',

  // ---------------------------------------------------------------- the daily path
  'Back to visit': 'विज़िट पर वापस',
  'Start my day': 'मेरा दिन शुरू करें',
  'Capture location': 'लोकेशन लें',
  'Location captured': 'लोकेशन ले ली',
  'Check in with the distance logged': 'दूरी दर्ज करके चेक इन करें',
  'Close it and check in here': 'उसे बंद करके यहाँ चेक इन करें',
  'No area recorded': 'कोई इलाक़ा दर्ज नहीं',
  'Note': 'नोट',
  'Required here': 'यहाँ ज़रूरी',
  'Why this shop, if it is off your route': 'ये दुकान क्यों, अगर रूट से बाहर है',
  'e.g. shop has moved, met the owner elsewhere': 'जैसे दुकान बदल गई, मालिक कहीं और मिले',
  'Showing your last saved details. Reconnect to refresh.': 'आपका आख़िरी सेव किया हुआ ब्यौरा दिख रहा है। ताज़ा करने के लिए दोबारा कनेक्ट करें।',
  'Tap to carry on, or to finish the visit.': 'जारी रखने या विज़िट पूरी करने के लिए दबाएँ।',
  'Loading your day…': 'आपका दिन लोड हो रहा है…',
  'Day running': 'दिन चल रहा है',
  'Active': 'चालू',
  'No beat planned for today.': 'आज के लिए कोई बीट तय नहीं है।',
  'Shops': 'दुकानें',
  'Loading the latest…': 'ताज़ा जानकारी आ रही है…',
  'KYC verified': 'KYC हो चुका है',
  'Call': 'कॉल करें',
  'Ready to take an order': 'ऑर्डर लेने के लिए तैयार',
  'Add a shop': 'दुकान जोड़ें',
  'Nothing matches that': 'इससे कुछ नहीं मिला',
  'No shops on this phone yet': 'इस फ़ोन में अभी कोई दुकान नहीं है',
  'Search by name, area or phone': 'नाम, इलाक़े या फ़ोन से खोजें',
  'Search shops': 'दुकानें खोजें',
  'Outside range': 'दायरे से बाहर',
  'Saved on this phone': 'इस फ़ोन में सेव है',
  'What to do here': 'यहाँ क्या करना है',
  'Sent': 'भेज दिया',
  'Stuck': 'अटका है',
  'Waiting': 'इंतज़ार में',
  'Saving photo…': 'फ़ोटो सेव हो रही है…',
  'What the next photo shows': 'अगली फ़ोटो में क्या है',
  'Anything worth telling your manager': 'मैनेजर को बताने लायक़ कुछ',
  'Take the photo at this shop': 'इस दुकान पर फ़ोटो लें',
  'You can still check in. Your manager will see the distance saved with this visit.': 'आप फिर भी चेक इन कर सकते हैं। इस विज़िट के साथ दूरी सेव होगी और मैनेजर उसे देखेंगे।',
  'Your day has not started yet. Start it and this shop will be waiting.': 'आपका दिन अभी शुरू नहीं हुआ है। शुरू करें, ये दुकान यहीं रहेगी।',
  'Tap to retake': 'दोबारा लेने के लिए दबाएँ',
  'Reason for the distance': 'दूरी की वजह',
  "Capture the shop's location": 'दुकान की लोकेशन लें',
  'Stand at the shopfront for the best pin': 'सबसे सही पिन के लिए दुकान के सामने खड़े हों',
  'What came of this visit?': 'इस विज़िट से क्या निकला?',
  'Why no order?': 'ऑर्डर क्यों नहीं?',
  'Visit outcome': 'विज़िट का नतीजा',
  'No Order': 'ऑर्डर नहीं',
  'Store checklist': 'दुकान की चेकलिस्ट',
  'Every answer is saved on this phone as you go.': 'हर जवाब साथ के साथ इस फ़ोन में सेव होता रहता है।',
  'Loading…': 'लोड हो रहा है…',
  'One moment.': 'एक पल।',
  'One moment…': 'एक पल…',
  'Refresh': 'ताज़ा करें',
  'Refreshing…': 'ताज़ा हो रहा है…',
  'Saving…': 'सेव हो रहा है…',
  'Close': 'बंद करें',
  'Remarks': 'टिप्पणी',
  'Choose one': 'एक चुनें',
  'Clear search': 'खोज हटाएँ',
  'Shop': 'दुकान',
  'Distance': 'दूरी',
  'Collected': 'वसूला गया',

  // ---------------------------------------------------------------- what the app says about itself
  'You are offline': 'आप ऑफ़लाइन हैं',
  'Saved on this phone': 'इस फ़ोन में सेव है',
  'Sending…': 'भेजा जा रहा है…',
  'Try again': 'दोबारा कोशिश करें',
  Cancel: 'रद्द करें',
  Done: 'हो गया',
  Language: 'भाषा',
}
