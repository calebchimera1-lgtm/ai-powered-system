# User manual

For everyone who uses the system in the shop. Each section says what you can do, where to find it
in the menu on the left, and what to watch out for. You only see the menus your role allows.

- [Getting started](#getting-started) (everyone)
- [Cashier](#cashier)
- [Inventory Officer](#inventory-officer)
- [Store Manager](#store-manager)
- [Super Admin](#super-admin)
- [Questions](#questions)

---

## Getting started

**Signing in.** Open the address your manager gave you (for example
`http://192.168.1.20:8080`) and sign in with your username or email.
- The first time, you must choose a new password: at least 8 characters, mixing letters with
  numbers or symbols, and not a common password.
- After 5 wrong passwords the account is locked for 15 minutes.
- Forgotten password? Ask the Super Admin for a reset link.

**The bell** (top right) shows notifications meant for you. Click one to go straight to the
item. See them all under **Account → Notifications**.

**Signing out.** Use the menu under your name, top right. On a shared till, always sign out
when you leave.

**My account** shows your details and the devices you are signed in on (you can sign out any of
them), and lets you change your password.

**Two-step sign-in (recommended for managers and administrators).** On **My account**, choose
**Set up** under *Two-step sign-in*, confirm your password, add the key to an authenticator app
on your phone (Google Authenticator, Microsoft Authenticator, Authy and similar), and type the
6-digit code it shows. From then on, signing in asks for your password and a fresh code. Lost
your phone? Ask the Super Admin to reset it.

Numbers are in Kenyan shillings (KES). Shelf prices include VAT.

---

## Cashier

### Sell at the till: Sales → Point of sale

1. **Scan** the barcode. The scanner types into the search box and the item is added. Scanning
   the same item again adds one more. With no barcode, type part of the name and pick the
   product.
2. Change the **quantity** if needed. For goods sold by weight, type the weight, for example `1.5`.
3. A **discount** of up to 10% can be given. More needs a manager.
4. Choose how the customer pays: **Cash**, **M-Pesa** or **Card**.
   - Cash: enter the amount received, and the change is shown.
   - M-Pesa: enter the transaction code from the customer's message.
5. Press **Complete sale**, then **Print receipt** if the customer wants one.

If the system says there is not enough stock, the shelf count and the system disagree. Tell the
inventory officer; do not sell it on another product's barcode.

**Clear sale** empties the cart. **New sale** starts the next customer after a sale.

### Customer returns: Sales → Returns

1. Find the original sale by its receipt number, then press **Start a return**.
2. Choose the items and quantities, and say whether the goods are resaleable or damaged.
3. Record the reason.

Your return waits for a manager's approval before the refund counts. Resaleable items go back
into stock; damaged ones do not.

### Your sales: Sales → Sales

This shows your receipts, with **Reprint**. **Reports → Daily sales** downloads your own sales
by day.

---

## Inventory Officer

### Products: Inventory → Products

- **Add or edit** a product: name, barcode (or generate one), category, unit, selling price
  (including VAT), VAT rate, minimum and maximum stock, and whether it has expiry dates.
- Filter by **low stock**, **out of stock** or **expiring soon**.
- A product's page shows its stock, batches with expiry dates, price history and movements.

### Receiving deliveries

You can receive a delivery in two ways.

**A. Scan the supplier's invoice (recommended): Purchasing → Scan invoices**
1. **Take photo** (on a phone) or **Choose file** (a photo or PDF, up to 10 MB). Lay the invoice
   flat, in good light, with all four corners showing.
2. Wait a few seconds while it is read.
3. **Check it against the paper**, field by field. Fields the system was unsure about are
   highlighted. For each line:
   - "Suggested" means the system guessed the product from its name. Press **Confirm** if it is
     right, or **Change** to pick the right one.
   - Unmatched lines need a product chosen.
   - If a number is wrong, correct it. The line total check tells you when quantity × price
     does not add up.
4. **Approve and receive**. Stock, average cost, batches and supplier prices update, and a
   goods-received note is created.

Notes:
- Nothing changes in stock until you approve.
- The same invoice cannot be received twice.
- If the photo is unreadable, **Reject** it with a reason and take a clearer one, or type the
  lines in by hand and approve.
- The system learns how each supplier names your products, so later invoices from them need
  fewer corrections.

**B. Enter it by hand: Purchasing → Goods received → Receive goods.** Choose the supplier and
enter each product, its quantity and its cost **excluding VAT**. Add the expiry date for
perishables. Press **Receive into stock**.

### Purchase orders: Purchasing → Purchase orders

Create an order, **Mark as sent** when it has gone to the supplier, and receive against it when
the goods arrive. Part deliveries are allowed. The quickest way to start an order is from
**Insights → Reorder suggestions** (below).

### Counting and correcting stock: Inventory → Adjustments

- **Stock count:** enter what you counted, and the system works out the difference.
- **Direct change:** add or remove a number of units, with a reason.
- **Write off:** damaged or expired goods.

Adjustments worth more than KES 5,000 wait for a manager. Every adjustment is recorded with who
made it and why. Many small corrections in one day, or large unexplained ones, appear as
irregularities for the manager. Count properly once rather than correcting repeatedly.

### Planning: Insights → Demand forecast and Reorder suggestions

- **Demand forecast** lists each product's expected sales for the next week and 4 weeks, and
  when it is likely to run out. Red means it may run out before a delivery could arrive.
- Click a product to see its sales chart. The solid line is actual sales, the dashed line the
  forecast, and the shaded band the range it will probably fall in.
- **Reorder suggestions** groups what to order by supplier. Adjust the quantities, then
  **Create draft purchase order**. Check the draft and send it.

Forecasts are estimates learnt from past sales. They cannot know about a promotion, a new
competitor or a supplier problem, so use your judgement.

### Reports

You can download: inventory valuation, purchase history, supplier performance, stock movement
summary, expired and damaged stock, and demand forecast (see [Reports](#reports-insights--reports)).

---

## Store Manager

You can do everything above, plus:

### Dashboard: Overview → Home

- **Today's sales, revenue, gross profit and stock value** for the period you choose (7 days,
  30 days, this month, 90 days or custom), optionally for one category.
- **Needs attention:** low stock, expiring soon, predicted shortages, approvals waiting and
  irregularities. Each one links to where it is dealt with.
- Revenue and profit by day, revenue by category, and fast and slow movers.

### Approvals

- **Returns** (Sales → Returns): approve or reject cashiers' refunds.
- **Large adjustments** (Inventory → Adjustments): approve or reject.
- **Scanned invoices** waiting more than 24 hours raise a notification.

You cannot approve your own return request; someone else must.

### Irregularities: Insights → Irregularities

The system compares each product's and each staff member's day with their own normal. It
raises an irregularity when something is far out of line, for example:
- 12 units adjusted out in a day when normally there are none
- a cashier taking 8 refunds in a day
- unusually high damage write-offs

Each alert explains what was unusual, the value involved, and what to check.

1. Open it, check (count the shelf, look at the movements, talk to the person involved).
2. Record the outcome: **Investigating**, **Issue found** or **No issue**, with a note.

Remember:
- **An irregularity is not an accusation.** Often there is a good explanation.
- Alerts about staff are visible only to managers and the Super Admin.
- Nobody can review an alert about their own activity.
- The share of checked alerts that turned out to be real issues is shown at the top of the
  page. It tells you how useful the alerts are in your shop.

### Money: Finance → Profit and sales, Expenses

**Profit and sales** shows revenue (excluding VAT and refunds), cost of goods sold, gross
profit and margin, by day, product, category and payment method. It also shows a net profit
estimate after stock losses and expenses. Record rent, salaries, power and so on under
**Expenses**, so the estimate is complete.

### Reports: Insights → Reports

1. Choose the period and, if you like, one category.
2. Pick the report and the format:
   - **PDF** to print or share
   - **Excel** to work with the numbers
   - **CSV** for other systems

| Report | What it shows |
|---|---|
| Inventory valuation | Stock on hand now, at cost and at selling price |
| Daily sales / Monthly sales | Sales, VAT, discounts, refunds, revenue and profit per day / month |
| Profitability | Revenue, cost and margin per product, and the net profit estimate |
| Purchase history | Every delivery, with supplier invoice and order number |
| Supplier performance | Spend, how much of each order arrived, on-time delivery, price rises |
| Stock movement summary | Opening stock, everything in and out, closing stock per product |
| Expired and damaged stock | Every write-off with batch, quantity and cost |
| Inventory irregularities | Irregularities in the period and how they were reviewed |
| Demand forecast | Latest forecast, expected stock-out dates and suggested orders |

Every download is recorded in the audit log.

---

## Super Admin

You can do everything above, plus:

### Staff accounts: Administration → Users

- Add a person, give them a role and a temporary password; they choose their own when they
  first sign in.
- **Deactivate** people who leave; do not share accounts.
- Forgotten password: create a **reset link** from the person's menu and give it to them; it
  works once and expires.
- **Sign out everywhere** if a phone or till may be in the wrong hands.
- **Reset two-step sign-in** if someone lost the phone with their authenticator app; they are
  signed out everywhere and can set it up again.

### Audit log: Administration → Audit log

This records who did what and when: sign-ins, user changes, prices, adjustments, approvals,
reviews, report downloads and backups. Filter it by type of activity or date.

### Backups: Administration → Backups

- A backup is made every night. **Back up now** before a big change.
- **Download** the database and the files, and keep a copy away from the shop's computer, for
  example on an external drive or in cloud storage. Do this at least once a week.
- Restoring replaces all data and is done by the person who looks after the computer (see the
  [installation guide](installation.md#4-backups-and-recovery)).

---

## Questions

**The system shows a different stock figure from the shelf.** Count the shelf and record a
**stock count** adjustment with the right reason. If it keeps happening for the same product,
look for a pattern: wrong barcode at the till, deliveries not recorded, breakages not written
off.

**A scanned invoice read a number wrong.** Correct it on the review screen before approving.
Corrections are counted, and the share of corrected lines is shown on the Scan invoices page.

**The forecast looks wrong for a product.** Check that its sales were recorded properly, for
example not sold under another product. New products, or those with less than 8 weeks of sales,
are marked "low confidence".

**Someone left the company.** Deactivate their account under **Users**. Their past records
stay, with their name on them.
