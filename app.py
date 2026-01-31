from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os, json, io
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# ─── data files ───────────────────────────────────────────────────────────
USERS_FILE   = 'users.json'    # must contain user accounts for login
BUDGETS_FILE = 'budgets.json'  # see example in chat
ENTRIES_FILE = 'entries.json'  # unified store for incomes & expenses

# ─── helpers ──────────────────────────────────────────────────────────────
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return default() if callable(default) else (default if default is not None else {})

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

# make sure files exist with sensible defaults
if not os.path.exists(USERS_FILE):
    # create a default admin user (username: admin, password: admin) - change later
    save_json(USERS_FILE, {"admin": {"password": "admin", "role": "Finance Manager", "department": "Main"}})
if not os.path.exists(BUDGETS_FILE):
    # example structure (you can replace contents later)
    save_json(BUDGETS_FILE, {
        "Main": {
            "total": 25000,
            "items": {
                "Budgeted Income": 25000,
                "Salaries": 2000,
                "SARS": 0,
                "Insurance": 300,
                "Security": 300,
                "Electricity": 1000,
                "Food": 300,
                "Pastoral Support Fund": 1500,
                "Maintenance": 7000,
                "Reserve/Investment": 1000
            }
        },
        "Building Fund": {"total": 0, "items": {}}
    })
if not os.path.exists(ENTRIES_FILE):
    save_json(ENTRIES_FILE, [])

# ─── auth ─────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = load_json(USERS_FILE, default=dict) or {}
        u = request.form.get('username','').strip()
        p = request.form.get('password','')
        if u in users and users[u].get('password') == p:
            session.update({
                'user': u,
                'role': users[u].get('role','Treasurer'),
                'dept': users[u].get('department','Main')
            })
            return redirect(url_for('dashboard'))
        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── dashboard ────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    role = session['role']
    dept = session['dept']
    now = datetime.now()

    # filters
    account = request.args.get('account', 'Main')
    try:
        selected_month = int(request.args.get('month', now.month))
        selected_year  = int(request.args.get('year', now.year))
    except ValueError:
        selected_month, selected_year = now.month, now.year

    entries = load_json(ENTRIES_FILE, default=list) or []
    budgets = load_json(BUDGETS_FILE, default=dict) or {}

    # filter entries visible to this user and in selected month/year
    def visible(e):
        # account-level rules
        acct_of_entry = e.get('account','Main')
        if role == 'Finance Manager':
            # Finance Manager may select only Main/Building Fund in UI - but keep general
            if account not in ('Main','Building Fund'):
                return False
            if acct_of_entry != account:
                return False
        elif role != 'Senior Pastor':
            # departmental treasurers only see their dept
            if acct_of_entry != dept:
                return False
        # Senior Pastor sees all

        # date filter
        try:
            d = parse_date(e.get('date','1970-01-01'))
        except Exception:
            return False
        return (d.year == selected_year and d.month == selected_month)

    month_entries = [e for e in entries if visible(e)]

    # totals for this month/account
    total_income = sum(float(e.get('amount',0)) for e in month_entries if e.get('type')=='Income')
    total_expense = sum(float(e.get('amount',0)) for e in month_entries if e.get('type')=='Expense')

    # budget lookup for the chosen account (or dept)
    key = account if role == 'Finance Manager' else dept
    raw_budget = budgets.get(key, None)

    # determine budget_total and items mapping
    budget_total = 0.0
    budget_items = {}
    if isinstance(raw_budget, dict):
        budget_total = float(raw_budget.get('total') or 0.0)
        budget_items = raw_budget.get('items') or {}
        # if no explicit total, sum items
        if not budget_total and budget_items:
            try:
                budget_total = sum(float(v) for v in budget_items.values())
            except Exception:
                budget_total = 0.0
    else:
        # raw number or missing
        try:
            budget_total = float(raw_budget or 0.0)
        except Exception:
            budget_total = 0.0

    # compute spent per budget item (for the selected month/account)
    item_spent = {name: 0.0 for name in budget_items.keys()}
    item_spent.setdefault('(Unassigned)', 0.0)

    for e in month_entries:
        if e.get('type') == 'Expense':
            b = e.get('budget_item') or '(Unassigned)'
            try:
                item_spent[b] = item_spent.get(b, 0.0) + float(e.get('amount',0))
            except Exception:
                pass

    # build table rows for template
    item_rows = []
    for name, bud in budget_items.items():
        spent = item_spent.get(name, 0.0)
        remaining = float(bud) - float(spent)
        item_rows.append({'name': name, 'budgeted': round(float(bud),2), 'spent': round(spent,2), 'remaining': round(remaining,2)})

    # include unassigned if there are unassigned expenses
    if item_spent.get('(Unassigned)',0.0) > 0:
        item_rows.append({'name': '(Unassigned)', 'budgeted': 0.0, 'spent': round(item_spent['(Unassigned)'],2), 'remaining': round(-item_spent['(Unassigned)'],2)})

    remaining = budget_total - total_expense

    # chart data for year (labels and series)
    labels = [f"{selected_year}-{mn:02d}" for mn in range(1,13)]
    def sum_for(lbl, kind):
        return sum(float(e.get('amount',0)) for e in entries if e.get('type')==kind and (role=='Senior Pastor' or e.get('account')==key) and str(e.get('date','')).startswith(lbl))
    chart_income = [sum_for(lbl,'Income') for lbl in labels]
    chart_expense = [sum_for(lbl,'Expense') for lbl in labels]

    return render_template('dashboard.html',
        user=user, role=role, dept=dept, now=now,
        account=account, selected_month=selected_month, selected_year=selected_year, current_year=now.year,
        total_income=round(total_income,2), total_expense=round(total_expense,2),
        budgets=budgets, budget_limit=round(budget_total,2), remaining=round(remaining,2),
        item_rows=item_rows,
        chart_labels=labels, chart_income=chart_income, chart_expense=chart_expense
    )

# ─── add income ───────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']; dept = session['dept']
    valid_accounts = ['Main','Building Fund'] if role=='Finance Manager' else ([] if role=='Senior Pastor' else [dept])

    if request.method == 'POST':
        account = request.form.get('account') if role=='Finance Manager' else dept
        if valid_accounts and account not in valid_accounts:
            flash("Account not permitted","danger"); return redirect(url_for('add_income'))
        try:
            entry = {
                'type': 'Income',
                'subtype': request.form.get('type',''),
                'account': account,
                'department': dept,
                'description': request.form.get('description',''),
                'date': request.form.get('date'),
                'amount': float(request.form.get('amount') or 0)
            }
        except ValueError:
            flash("Invalid amount","danger"); return redirect(url_for('add_income'))

        entries = load_json(ENTRIES_FILE, default=list) or []
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)
        flash("Income saved","success")
        return redirect(url_for('dashboard'))

    return render_template('add_income.html', valid_accounts=valid_accounts, role=role, now=datetime.now())

# ─── add expense (with budget_item) ────────────────────────────────────────
@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']; dept = session['dept']
    valid_accounts = ['Main','Building Fund'] if role=='Finance Manager' else ([] if role=='Senior Pastor' else [dept])
    budgets = load_json(BUDGETS_FILE, default=dict) or {}

    if request.method == 'POST':
        account = request.form.get('account') if role=='Finance Manager' else dept
        if valid_accounts and account not in valid_accounts:
            flash("Account not permitted","danger"); return redirect(url_for('add_expense'))
        budget_item = request.form.get('budget_item') or None
        try:
            entry = {
                'type': 'Expense',
                'subtype': request.form.get('type',''),
                'account': account,
                'department': dept,
                'description': request.form.get('description',''),
                'date': request.form.get('date'),
                'amount': float(request.form.get('amount') or 0),
                'budget_item': budget_item
            }
        except ValueError:
            flash("Invalid amount","danger"); return redirect(url_for('add_expense'))

        entries = load_json(ENTRIES_FILE, default=list) or []
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)
        flash("Expense saved","success")
        return redirect(url_for('dashboard'))

    # build budget_items for selected account (if any)
    account_for_form = request.args.get('account', valid_accounts[0] if valid_accounts else dept)
    b = budgets.get(account_for_form, {})
    budget_items = []
    if isinstance(b, dict):
        budget_items = list(b.get('items',{}).keys())

    return render_template('add_expense.html', valid_accounts=valid_accounts, role=role, now=datetime.now(), budget_items=budget_items, account_for_form=account_for_form)

# ─── manage budgets ───────────────────────────────────────────────────────
@app.route('/manage_budgets', methods=['GET','POST'])
def manage_budgets():
    if session.get('role') != 'Finance Manager':
        return redirect(url_for('dashboard'))
    budgets = load_json(BUDGETS_FILE, default=dict) or {}
    if request.method == 'POST':
        # For simple UI: update flat totals for Main/Building Fund if sent
        for acc in ['Main','Building Fund']:
            val = request.form.get(acc)
            if val is not None and val != '':
                try:
                    budgets.setdefault(acc, {})['total'] = float(val)
                except Exception:
                    pass
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated","success")
        return redirect(url_for('manage_budgets'))
    return render_template('manage_budgets.html', budgets=budgets)

# ─── report & exports ────────────────────────────────────────────────────
@app.route('/report')
def report():
    dept_f = request.args.get('department','')
    frm = request.args.get('from_date','')
    to  = request.args.get('to_date','')
    entries = load_json(ENTRIES_FILE, default=list) or []

    def ok(e):
        if dept_f and e.get('department','') != dept_f: return False
        if frm and e.get('date','') < frm: return False
        if to and e.get('date','') > to: return False
        return True

    data = [e for e in entries if ok(e)]
    data.sort(key=lambda x: x.get('date',''), reverse=True)
    return render_template('report.html', data=data, department_filter=dept_f, from_date=frm, to_date=to)

@app.route('/export-excel')
def export_excel():
    dept_f = request.args.get('department','')
    frm = request.args.get('from_date','')
    to  = request.args.get('to_date','')
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and e.get('department','') != dept_f: continue
        if frm and e.get('date','') < frm: continue
        if to and e.get('date','') > to: continue
        rows.append({
            'Date': e.get('date',''),
            'Department': e.get('department',''),
            'Type': e.get('type',''),
            'Subtype': e.get('subtype',''),
            'Budget Item': e.get('budget_item',''),
            'Description': e.get('description',''),
            'Amount (R)': e.get('amount',0)
        })
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    output.seek(0)
    fn = f"report_{dept_f or 'all'}_{frm}_{to}.xlsx"
    return send_file(output, download_name=fn, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export-pdf')
def export_pdf():
    dept_f = request.args.get('department','')
    frm = request.args.get('from_date','')
    to  = request.args.get('to_date','')
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and e.get('department','') != dept_f: continue
        if frm and e.get('date','') < frm: continue
        if to and e.get('date','') > to: continue
        rows.append(e)
    rows.sort(key=lambda x: x.get('date',''), reverse=True)
    return render_template('report_pdf.html', data=rows, now=lambda: datetime.now())

# ─── run ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',10000)), debug=True)
