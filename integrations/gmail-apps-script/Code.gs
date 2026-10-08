/** PoliticsHub Brief — free sender-account relay for Google Apps Script.
 * Deploy ONLY while signed in to politicshub.in@gmail.com.
 * Add Script Property PH_RELAY_TOKEN with a unique 32+ character random value.
 * Execute as: Me; Access: Anyone. Every request still requires the secret token.
 * Never place the token into this source file, GitHub, or public documents.
 */
const POLITICSHUB_SENDER = 'politicshub.in@gmail.com';

function relayJson_(value) {
  return ContentService
    .createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  const props = PropertiesService.getScriptProperties();
  const secret = props.getProperty('PH_RELAY_TOKEN');
  if (!secret || secret.length < 32) return relayJson_({ok:false});
  if (!e || !e.postData || !e.postData.contents ||
      e.postData.contents.length > 75000) return relayJson_({ok:false});

  let data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (err) {
    return relayJson_({ok:false});
  }
  if (!data || typeof data !== 'object' ||
      typeof data.token !== 'string' || data.token !== secret) {
    return relayJson_({ok:false});
  }

  // Prevent accidental deployment under a different Google account.
  const identity = String(Session.getEffectiveUser().getEmail() || '').toLowerCase();
  if (identity !== POLITICSHUB_SENDER) return relayJson_({ok:false});

  const recipient = String(data.to || '').trim().toLowerCase();
  const subject = String(data.subject || '').trim();
  const textBody = String(data.text || '').trim();
  const htmlBody = String(data.html || '').trim();
  const requestId = String(data.idempotency_key || '');
  if (!/^[a-z0-9._%+\-]+@[a-z0-9.-]+\.[a-z]{2,}$/.test(recipient) ||
      recipient.length > 254 || subject.length < 1 || subject.length > 180 ||
      textBody.length < 1 || textBody.length > 20000 ||
      htmlBody.length > 50000 || !/^[a-f0-9]{64}$/.test(requestId)) {
    return relayJson_({ok:false});
  }

  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return relayJson_({ok:false});
  try {
    const cache = CacheService.getScriptCache();
    const cacheKey = 'newsletter:' + requestId;
    if (cache.get(cacheKey)) return relayJson_({ok:true,duplicate:true});
    if (MailApp.getRemainingDailyQuota() < 1) return relayJson_({ok:false});
    const options = {
      name: 'PoliticsHub.in',
      replyTo: POLITICSHUB_SENDER
    };
    if (htmlBody) options.htmlBody = htmlBody;
    // Google's authorized Apps Script Mail service sends from the owner.
    MailApp.sendEmail(recipient, subject, textBody, options);
    cache.put(cacheKey, '1', 600);
    return relayJson_({ok:true});
  } catch (err) {
    // Do not echo tokens, recipient addresses, or internals to the caller.
    console.error('Newsletter send failed: ' + (err && err.name || 'Error'));
    return relayJson_({ok:false});
  } finally {
    lock.releaseLock();
  }
}
