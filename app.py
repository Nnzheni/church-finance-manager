# app.py — Cleaned & consistent version
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os, json, io
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# ─── DATA FILES ─────────────────────────────────────────────────────────────
USERS_FILE   = 'users.json'    # { "admin": {"password":"x","role":"Finance Manager","department":"Main"} }
BUDGETS_FILE = 'budgets.json'  # e.g. { "Main": 65000, "Building Fund": 15000, ... } (or migrated structure)
ENTRIES_FILE = 'entries.json'  # unified store for Income & Expense entries

# ─── UTILITIES ──────────────────────────────────────────────────────────────
def load_json(path, default=None):
    """Load JSON file. If missing, return default (callable or value)."""
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    if callable(default):
        return default()
    return default if default is not None else []

def save_json(path, data):
    """Write JSON to file with indentation."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

# ─── AUTH ──────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        users = load_json(USERS_FILE, default=dict)
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        if u and u in users and users[u].get('password') == p:
            # store user, role, dept consistently
            session['user'] = u
            session['role'] = users[u].get('role', '')
            session['dept'] = users[u].get('department', '')
            return redirect(url_for('dashboard'))
        flash("Invalid credentials", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── DASHBOARD ─────────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    role = session.get('role', '')
    dept = session.get('dept', '')
    now = datetime.now()

    # filters
    acct = request.args.get('account', 'Main')
    try:
        m = int(request.args.get('month', now.month))
        y = int(request.args.get('year', now.year))
    except ValueError:
        m, y = now.month, now.year

    # load data
    entries = load_json(ENTRIES_FILE, default=list) or []
    budgets = load_json(BUDGETS_FILE, default=dict) or {}

    # selection logic (who sees what)
    def keep(e):
        # e must have: 'account', 'date', 'type', 'amount'
        if role == 'Finance Manager':
            if acct not in ('Main', 'Building Fund'):
                return False
            if e.get('account') != acct:
                return False
        elif role != 'Senior Pastor':
            # departmental treasurer
            if e.get('account') != dept:
                return False
        # Senior Pastor sees all accounts

        try:
            d = parse_date(e.get('date'))
        except Exception:
            return False
        return d.year == y and d.month == m

    month_entries = [e for e in entries if keep(e)]

    total_income = sum(float(e.get('amount', 0)) for e in month_entries if e.get('type') == 'Income')
    total_expense = sum(float(e.get('amount', 0)) for e in month_entries if e.get('type') == 'Expense')
    balance = total_income - total_expense

    key = acct if role == 'Finance Manager' else dept
    budget_limit = float(budgets.get(key, 0.0))
    remaining = budget_limit - total_expense

    # chart data (12 months)
    labels = [f"{y}-{mn:02d}" for mn in range(1, 13)]

    def sum_for(lbl, kind):
        return sum(
            float(e.get('amount', 0))
            for e in entries
            if e.get('type') == kind
            and (role == 'Senior Pastor' or e.get('account') == key)
            and e.get('date', '').startswith(lbl)
        )

    chart_income = [sum_for(lbl, 'Income') for lbl in labels]
    chart_expense = [sum_for(lbl, 'Expense') for lbl in labels]

    return render_template(
        'dashboard.html',
        user=user,
        role=role,
        dept=dept,
        now=now,
        selected_month=m,
        selected_year=y,
        current_year=now.year,
        account=acct,
        total_income=round(total_income, 2),
        total_expense=round(total_expense, 2),
        balance=round(balance, 2),
        budget_limit=round(budget_limit, 2),
        remaining=round(remaining, 2),
        chart_labels=labels,
        chart_income=chart_income,
        chart_expense=chart_expense
    )

# ─── ADD INCOME ────────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET', 'POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    dept = session.get('dept')  # template supplies dept in hidden input for non-FM users

    # allowed accounts for Finance Manager, others default to their dept, senior pastor view-only
    if role == 'Finance Manager':
        valid_accounts = ['Main', 'Building Fund']
    elif role == 'Senior Pastor':
        valid_accounts = []   # Senior Pastor should not POST
    else:
        valid_accounts = [dept]

    if request.method == 'POST':
        try:
            # determine account
            account = request.form.get('account', dept)
            if role == 'Finance Manager' and account not in valid_accounts:
                flash('Account not permitted', 'danger')
                return redirect(url_for('dashboard'))
            if role == 'Senior Pastor':
                flash('Senior Pastor is view-only', 'danger')
                return redirect(url_for('dashboard'))

            amount = float(request.form['amount'])
            subtype = request.form.get('type', '').strip()
            description = request.form.get('description', '').strip()
            date = request.form['date']

            entry = {
                'type': 'Income',
                'subtype': subtype,
                'account': account,
                'department': dept,
                'description': description,
                'date': date,
                'amount': amount
            }

            entries = load_json(ENTRIES_FILE, default=list)
            entries.append(entry)
            save_json(ENTRIES_FILE, entries)

            flash('Income saved', 'success')
            return redirect(url_for('dashboard'))
        except Exception as exc:
            # helpful error message in logs and flash to UI
            app.logger.exception("Failed saving income")
            flash(f"Failed to save income: {str(exc)}", "danger")
            return redirect(url_for('add_income'))

    # GET -> render form
    return render_template('add_income.html', valid_accounts=valid_accounts, role=role, now=datetime.now())

# ─── ADD EXPENSE ───────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET', 'POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    dept = session.get('dept')

    if role == 'Finance Manager':
        valid_accounts = ['Main', 'Building Fund']
    elif role == 'Senior Pastor':
        valid_accounts = []
    else:
        valid_accounts = [dept]

    if request.method == 'POST':
        try:
            account = request.form.get('account', dept)
            if role == 'Finance Manager' and account not in valid_accounts:
                flash('Account not permitted', 'danger')
                return redirect(url_for('dashboard'))
            if role == 'Senior Pastor':
                flash('Senior Pastor is view-only', 'danger')
                return redirect(url_for('dashboard'))

            amount = float(request.form['amount'])
            subtype = request.form.get('type', '').strip()
            description = request.form.get('description', '').strip()
            date = request.form['date']

            entry = {
                'type': 'Expense',
                'subtype': subtype,
                'account': account,
                'department': dept,
                'description': description,
                'date': date,
                'amount': amount
            }

            entries = load_json(ENTRIES_FILE, default=list)
            entries.append(entry)
            save_json(ENTRIES_FILE, entries)

            flash('Expense saved', 'success')
            return redirect(url_for('dashboard'))
        except Exception as exc:
            app.logger.exception("Failed saving expense")
            flash(f"Failed to save expense: {str(exc)}", "danger")
            return redirect(url_for('add_expense'))

    return render_template('add_expense.html', valid_accounts=valid_accounts, role=role, now=datetime.now())

# ─── BUDGETS ────────────────────────────────────────────────────────────────
@app.route('/budgets', methods=['GET', 'POST'])
def manage_budgets():
    if session.get('role') != 'Finance Manager':
        return redirect(url_for('dashboard'))

    budgets = load_json(BUDGETS_FILE, default=dict) or {}
    if request.method == 'POST':
        for acc in ['Main', 'Building Fund']:
            raw = request.form.get(acc, budgets.get(acc, 0))
            try:
                budgets[acc] = float(raw or 0)
            except ValueError:
                budgets[acc] = budgets.get(acc, 0)
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated", "success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)

# ─── REPORT & EXPORT ───────────────────────────────────────────────────────
@app.route('/report')
def report():
    dept_f = request.args.get('department', '').strip()
    frm = request.args.get('from_date', '')
    to = request.args.get('to_date', '')
    entries = load_json(ENTRIES_FILE, default=list) or []

    def ok(e):
        if dept_f and e.get('department') != dept_f:
            return False
        if frm and e.get('date', '') < frm:
            return False
        if to and e.get('date', '') > to:
            return False
        return True

    data = sorted([e for e in entries if ok(e)], key=lambda x: x.get('date', ''), reverse=True)
    return render_template('report.html', data=data, department_filter=dept_f, from_date=frm, to_date=to)

@app.route('/export-excel')
def export_excel():
    dept_f = request.args.get('department', '').strip()
    frm = request.args.get('from_date', '')
    to = request.args.get('to_date', '')
    entries = load_json(ENTRIES_FILE, default=list) or []

    rows = []
    for e in entries:
        if dept_f and e.get('department') != dept_f: continue
        if frm and e.get('date', '') < frm: continue
        if to and e.get('date', '') > to: continue
        rows.append({
            'Date': e.get('date', ''),
            'Department': e.get('department', ''),
            'Type': e.get('type', ''),
            'Subtype': e.get('subtype', ''),
            'Description': e.get('description', ''),
            'Amount (R)': e.get('amount', 0)
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    output.seek(0)
    fn = f"report_{dept_f or 'all'}_{frm}_{to}.xlsx"
    return send_file(output, download_name=fn, as_attachment=True,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export-pdf')
def export_pdf():
    dept_f = request.args.get('department', '').strip()
    frm = request.args.get('from_date', '')
    to = request.args.get('to_date', '')
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and e.get('department') != dept_f: continue
        if frm and e.get('date', '') < frm: continue
        if to and e.get('date', '') > to: continue
        rows.append(e)
    rows.sort(key=lambda x: x.get('date', ''), reverse=True)
    return render_template('report_pdf.html', data=rows, now=lambda: datetime.now())

# ─── RUN ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=True)
