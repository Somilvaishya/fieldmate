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

  // ---------------------------------------------------------------- what the app says about itself
  'You are offline': 'आप ऑफ़लाइन हैं',
  'Saved on this phone': 'इस फ़ोन में सेव है',
  'Sending…': 'भेजा जा रहा है…',
  'Try again': 'दोबारा कोशिश करें',
  Cancel: 'रद्द करें',
  Done: 'हो गया',
  Language: 'भाषा',
}
