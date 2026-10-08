# PoliticsHub Brief: free Google-account mail relay

This is an **optional** alternative to Gmail SMTP when automated messages receive
Gmail error \`550 5.7.30\` (DKIM failure). It uses the sender account's own
Google Apps Script / Mail service to send messages. There is no third-party mail
service or paid subscription involved.

**Not active until configured.** The current \`GMAIL_APP_PASSWORD\` SMTP path remains
untouched and active until both new Vercel variables are configured.

## One-time setup (use politicshub.in@gmail.com)

1. Sign into **politicshub.in@gmail.com**, then open
   [Google Apps Script](https://script.google.com/home/projects/create).
2. Create a new project and paste the contents of
   [Code.gs](./Code.gs). Save.
3. In **Project Settings → Script Properties**, add a property named
   \`PH_RELAY_TOKEN\`. Generate a unique random secret of **at least 32 characters**.
   Do not reuse the Gmail app password, your admin login, or CRON_SECRET.
   Keep the token in a private password manager; **never share it in chat or commit
   it to GitHub**.
4. Select the **authorizeMail** function and click **Run**. Review Google's
   permission screen for sending email. This function only reads your remaining
   daily email quota; it does not send a message. It refuses to authorize under
   a Gmail account other than politicshub.in@gmail.com.
5. **Deploy → New deployment → Web app**.
   - **Execute as**: Me (the PoliticsHub sender account)
   - **Who has access**: Anyone (the app checks the secret on every POST)
   - Copy the URL ending in **/exec**.
6. On the Vercel **news-bot** project, add these **Production** environment
   variables (mark the token as **Sensitive**):
   - \`NEWSLETTER_GMAIL_RELAY_URL\`: the exact web-app URL
   - \`NEWSLETTER_GMAIL_RELAY_TOKEN\`: the **same** value as the Script Property
     \`PH_RELAY_TOKEN\`
7. Trigger a new **production** deployment (the current build cannot pick up
   newly saved variables). Do not delete the existing Gmail app password yet.
8. Submit **one** newsletter signup with a real, consenting adult's email,
   verify receipt in Inbox and check the Gmail message's "Show original" for
   authentication results. Do not send repeated retries to rejected recipients.

Only if the relay is fully configured will PoliticsHub send through Google Apps
Script instead of smtp.gmail.com. If the relay returns an error, the application
**reports failure** instead of quietly falling back to the broken SMTP path.

## Important limitations

- Google's consumer Apps Script email quota is approximately **100 recipients/day**
  at the time of writing; quota limits can change. See
  https://developers.google.com/apps-script/guides/services/quotas
- Script deployment must be authorized by the owner of the sending Gmail address.
  It does not give access to any other Gmail account.
- Because the Apps Script web-app endpoint may be publicly reachable, **keep the
  token secret and sufficiently random**. The service refuses unauthenticated,
  oversized or malformed requests and applies idempotency and Google's mail
  quotas to guard against abuse.
- Google controls DKIM. This alternative may improve deliverability but does **not**
  guarantee Inbox placement or resolve every sender-reputation problem.
- MailApp does not expose the full RFC822 outgoing header interface, so automated
  one-click \`List-Unsubscribe\` headers cannot be set through this route. The
  existing HTML/text unsubscribe links remain in the email body.
- Do not activate if sender Google account authorization or web-app access policy
  does not permit this setup.

This setup does not change subscriptions, consent requirements, email templates,
or the existing newsletter database.
