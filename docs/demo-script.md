# Live demonstration script

A 12 to 15 minute walk-through of the brief's demonstration scenario (section 11), for a project
defence. It goes with the slide deck: present slides 1–5, run this demo, then present the AI
results (slides 6–14). All data is **synthetic demo data**.

## The day before

1. Install the system on the presentation laptop by following [installation.md](installation.md),
   including the image build on a normal connection. That one step was not verified in the
   project's own sandbox.
2. Load the demo data, then wait a minute for the worker to finish its forecast and scan.
   The second command takes about 2 minutes:

   ```bash
   docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_users
   ```

   ```bash
   docker compose exec -e ENVIRONMENT=development api python -m scripts.seed_demo_catalog --history-days 180
   ```

3. Print `sample-data/invoices/invoice-004-inclusive-clean.jpg` on A4, plus
   `invoice-011-classic-phone.jpg` as a spare. Or keep the files on the phone or desktop to
   upload.
4. Run the whole script once. Then make a backup (**Administration → Backups → Back up now**,
   signed in as a Super Admin) so you can reset to this state (see the end of this script).
5. Open four browser windows, or four profiles, one per account below, so you never have to
   sign out on stage. Zoom to 125% so the room can read it.

| Window | Username | Password | Role |
|---|---|---|---|
| 1 | `admin` | `Demo@2026!` | Super Admin |
| 2 | `inventory` | `Demo@2026!` | Inventory Officer |
| 3 | `cashier` | `Demo@2026!` | Cashier |
| 4 | `manager` | `Demo@2026!` | Store Manager |

## The demonstration

Timings are guides. **Say** lines are suggestions; put them in your own words.

### 1. An administrator signs in · window 1 · 30 s

Sign in as `admin`.

> **Say:** "Four roles, four views. The server checks every permission. Hiding a button is
> not enough."

### 2. The administrator registers a supplier · window 1 · 1 min

1. **Purchasing → Suppliers → Add supplier**.
2. Enter "Lakeview Traders (Demo)", a contact, a phone and a KRA PIN such as `P051234567Q`.
3. Save. Point out the three suppliers already there from the demo data.

> **Say:** "The supplier's KRA PIN is what the invoice reader uses to recognise them."

### 3. The officer uploads a supplier invoice · window 2 · 1 min

1. As `inventory`: **Purchasing → Scan invoices**.
2. **Take photo** of the printed invoice 004 with a phone signed in as `inventory`, or
   **Choose file** on the laptop.

> **Say:** "The photo goes to a background worker, so the page stays responsive."

### 4. The AI extracts the invoice · window 2 · 2 min

The review screen opens after a few seconds. Walk through it:
- **Supplier:** Nairobi Wholesale Distributors (Demo), recognised by its PIN.
- **Invoice details:** number SI/5040, date 24 Oct 2026, total KES 27,930.06.
- **Lines:** three, white sugar 20, cooking oil 30 and rice 36, each matched to a catalogue
  product. "PISH RICE 2KG" matched *Pishori Rice 2kg* although the supplier abbreviates it.
- **Line prices include VAT** is ticked. Stock costs are recorded without VAT.

> **Say:** "It cleaned the image, read it with Tesseract, then used arithmetic, quantity times
> price equals total, to decide which number is which."

**Optional (+1 min):** upload `invoice-011-classic-phone.jpg` to show an imperfect read:
- The invoice number "S1I/1035" is flagged *Not read clearly*. Correct it to SI/1035.
- "1L" was read as "2L", so the line is unmatched. Choose *Bottled Water 1L*.

> **Say:** "This is why a person always approves."

### 5. The officer reviews and approves · window 2 · 30 s

Note the stock of White Sugar 2kg first (Inventory → Products), then press **Approve and
receive** and confirm.

### 6. Stock updates automatically · window 2 · 30 s

1. Open **View goods-received note**: it is marked as coming from a scanned invoice.
2. Open the product: stock has risen by exactly 20.

> **Say:** "Average cost and expiry batches updated too. The same invoice can't be received
> twice. Try uploading it again and it is refused."

### 7. A cashier records sales · window 3 · 1 min

1. As `cashier`: **Point of sale**.
2. Type "sugar" and pick White Sugar 2kg. Add maize flour. Set a quantity of 3.
3. Choose **M-Pesa** and enter a code such as `SKD4H2L9QX`.
4. **Complete sale**, then **Print receipt** to show it.

### 8. Stock decreases · window 2 · 20 s

Refresh the sugar product page: stock fell by the quantity sold.

### 9. The financial dashboard updates · window 4 · 1.5 min

As `manager`, on **Home**:
- **Today's sales** includes the sale just made, excluding VAT.
- Switch the period to **7 days**, then the category to **Dry goods**.
- Show the attention tiles (low stock, expiring, predicted shortages, approvals).
- **Insights → Reports → Profitability → PDF**: open it.

> **Say:** "Cooking oil shows a loss here. In the simulated history its supplier cost rose 12%
> but the shelf price didn't. That's exactly what this report is for."

### 10. The forecasting engine predicts demand · window 4 · 1.5 min

1. **Insights → Demand forecast.** Products are listed by how soon they run out.
2. Open **White Sugar 2kg**. Point at:
   - the solid actual line, the dashed forecast, the shaded 80% range and the Today line
   - the reorder point and suggested order
   - "How the model was chosen"
3. **Reorder suggestions → Create draft purchase order.**

> **Say:** "Six models competed on this product's own past weeks, and the most accurate one
> was used."

### 11. Anomaly detection finds unusual movements · windows 2 and 4 · 2 min

1. As `inventory`: **Inventory → Products → Pishori Rice 2kg → Adjust stock**.
2. Choose **Add or remove**, direction **Remove**, quantity **12**, reason **Stock count
   correction**. Save.
3. As `manager`: **Insights → Irregularities → Check now**. After a few seconds, refresh.
   - An *Unexplained stock loss* alert appears: 12 units adjusted out today against a normal
     of 0, with the KES value and a suggested check.
   - A staff-related alert about the officer appears too. It is visible only to managers.
4. Open it, choose **Investigating**, add a note and save.

> **Say:** "It's a prompt to investigate, never an accusation. Each review outcome is
> recorded, which tells us how often these alerts are right in a real shop."

The demo data also contains earlier irregularities from the simulated history. These are
useful if the live one is slow to appear.

## If something goes wrong

| Problem | What to do |
|---|---|
| The invoice stays "Waiting to be read" | The worker is down. Run `docker compose start worker`. Meanwhile show `docs/ai/ocr-evaluation.md` |
| A field is misread on the live photo | Good: correct it on screen. That is the review step working |
| The phone can't reach the laptop | Upload the file from the laptop instead (Choose file) |
| The irregularity doesn't appear | Make sure the adjustment was saved (it is listed under Inventory → Adjustments), then **Check now** again. Otherwise open one of the earlier alerts |
| Anything else | Show the automated version: `backend/tests/scenario/test_demo_scenario.py` runs all 11 steps |

## Reset between rehearsals

Restore the backup made the day before (it takes about 15 seconds):

```bash
make backups
```

```bash
make restore NAME=<the backup you made>
```
