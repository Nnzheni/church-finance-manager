# app.py - Cleaned & robust single-file Flask app (entries.json + budgets.json)
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, jsonify
import os, json, io
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")

# ─── DATA FILES ─────────────────────────────────────────────────────────────
USERS_FILE   = 'users.json'
BUDGETS_FILE = 'budgets.json'
ENTRIES_FILE = 'entries.json'   # unified store for both Income & Expense

# ─── UTILITIES ──────────────────────────────────────────────────────────────
def load_json(path, default=None):
    """Load JSON file, return default if not present"""
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    # default: if callable, call it; else return default value (or empty container)
    if default is None:
        return None
    return default() if callable(default) else default

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

def get_budget_limit(budgets, key):
    """
    Return a numeric budget limit for `key`. Accepts several shapes:
      - budgets[key] is a number -> returned
      - budgets[key] is a dict with 'total'/'limit' -> returned
      - budgets[key] is an items dict -> sum numeric children
    Otherwise returns 0.0
    """
    val = budgets.get(key, 0)
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        # prefer explicit total fields
        for candidate in ('total', 'limit', 'budget', 'amount'):
            if candidate in val:
                try:
                    return float(val[candidate])
                except (ValueError, TypeError):
                    pass
        # sum numeric children (items)
        total = 0.0
        for v in val.values():
            try:
                if isinstance(v, dict):
                    # nested item may have 'amount' or 'value'
                    for c in ('amount', 'value', 'budget'):
                        if c in v:
                            total += float(v[c])
                            break
                else:
                    total += float(v)
            except (ValueError, TypeError):
                continue
        return total
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

# ─── AUTH ──────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        users = load_json(USERS_FILE, default=dict) or {}
        u = request.form.get('username','').strip()
        p = request.form.get('password','')
        if u in users and users[u].get('password') == p:
            session.update({
                'user': u,
                'role': users[u].get('role','Member'),
                'dept': users[u].get('department','Main')
            })
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
    role = session['role']
    dept = session['dept']
    now = datetime.now()

    # filters (account, month, year)
    acct = request.args.get('account', 'Main')
    m    = int(request.args.get('month', now.month))
    y    = int(request.args.get('year', now.year))

    entries = load_json(ENTRIES_FILE, default=list) or []
    budgets = load_json(BUDGETS_FILE, default=dict) or {}

    # filter entries user may see for selected month
    def keep(e):
        # role-based visibility
        if role == 'Finance Manager':
            # Finance Manager may choose only Main or Building Fund in UI
            if acct not in ('Main', 'Building Fund'):
                return False
            if e.get('account') != acct:
                return False
        elif role != 'Senior Pastor':
            # departmental treasurers see only entries for their department
            if e.get('account') != dept:
                return False
        # Senior Pastor sees all

        # filter by month/year
        try:
            d = parse_date(e.get('date', '1970-01-01'))
        except Exception:
            return False
        return (d.year == y and d.month == m)

    month_entries = [e for e in entries if keep(e)]

    total_income  = sum(e.get('amount', 0) for e in month_entries if e.get('type') == 'Income')
    total_expense = sum(e.get('amount', 0) for e in month_entries if e.get('type') == 'Expense')

    key = acct if role == 'Finance Manager' else dept
    budget_limit = get_budget_limit(budgets, key)
    remaining = budget_limit - total_expense

    # chart: simple per-month for year y
    labels = [f"{y}-{mn:02d}" for mn in range(1,13)]
    def sum_for(lbl, kind):
        return sum(
            e.get('amount', 0)
            for e in entries
            if e.get('type') == kind
            and (role == 'Senior Pastor' or e.get('account') == key)
            and e.get('date','').startswith(lbl)
        )
    chart_income  = [sum_for(lbl, 'Income') for lbl in labels]
    chart_expense = [sum_for(lbl, 'Expense') for lbl in labels]

    return render_template('dashboard.html',
        user=user, role=role, dept=dept, now=now,
        selected_month=m, selected_year=y, current_year=now.year,
        account=acct,
        total_income=total_income, total_expense=total_expense,
        balance=total_income - total_expense, budget_limit=budget_limit,
        remaining=remaining,
        chart_labels=labels, chart_income=chart_income, chart_expense=chart_expense
    )

# ─── ADD INCOME ────────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']; dept = session['dept']
    valid_accounts = ['Main','Building Fund'] if role == 'Finance Manager' else ([] if role=='Senior Pastor' else [dept])

    if request.method == 'POST':
        account = request.form.get('account') if role == 'Finance Manager' else dept
        if account not in valid_accounts:
            flash("Account not permitted", "danger"); return redirect(url_for('dashboard'))

        try:
            entry = {
                'type': 'Income',
                'subtype': request.form.get('type','').strip(),
                'account': account,
                'department': dept,
                'description': request.form.get('description','').strip(),
                'date': request.form.get('date'),
                'amount': float(request.form.get('amount', '0') or 0)
            }
        except ValueError:
            flash("Amount must be numeric", "danger"); return redirect(url_for('add_income'))

        entries = load_json(ENTRIES_FILE, default=list) or []
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)

        flash("Income saved", "success")
        return redirect(url_for('dashboard'))

    return render_template('add_income.html', valid_accounts=valid_accounts, role=role, now=datetime.now())

# ─── ADD EXPENSE ───────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))
    role = session['role']; dept = session['dept']
    valid_accounts = ['Main','Building Fund'] if role == 'Finance Manager' else ([] if role=='Senior Pastor' else [dept])

    if request.method == 'POST':
        account = request.form.get('account') if role == 'Finance Manager' else dept
        if account not in valid_accounts:
            flash("Account not permitted", "danger"); return redirect(url_for('dashboard'))

        try:
            entry = {
                'type': 'Expense',
                'subtype': request.form.get('type','').strip(),
                'account': account,
                'department': dept,
                'description': request.form.get('description','').strip(),
                'date': request.form.get('date'),
                'amount': float(request.form.get('amount', '0') or 0)
            }
        except ValueError:
            flash("Amount must be numeric", "danger"); return redirect(url_for('add_expense'))

        entries = load_json(ENTRIES_FILE, default=list) or []
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)

        flash("Expense saved", "success")
        return redirect(url_for('dashboard'))

    return render_template('add_expense.html', valid_accounts=valid_accounts, role=role, now=datetime.now())

# ─── MANAGE BUDGETS ───────────────────────────────────────────────────────
@app.route('/budgets', methods=['GET','POST'])
def manage_budgets():
    if session.get('role') != 'Finance Manager':
        return redirect(url_for('dashboard'))
    budgets = load_json(BUDGETS_FILE, default=dict) or {}

    if request.method == 'POST':
        # Accept either a simple number or a JSON structure in the form input
        # For simplicity: we expect text fields for Main / Building Fund with numeric amounts
        for acc in ['Main', 'Building Fund']:
            v = request.form.get(acc)
            if v is None:
                continue
            # try parse number first
            try:
                budgets[acc] = float(v)
            except Exception:
                # if not a number, try parse JSON (for itemised budgets)
                try:
                    parsed = json.loads(v)
                    budgets[acc] = parsed
                except Exception:
                    # ignore invalid
                    continue
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated", "success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)

# ─── REPORT & EXPORT ───────────────────────────────────────────────────────
@app.route('/report')
def report():
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

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
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and e.get('department','') != dept_f: continue
        if frm and e.get('date','') < frm: continue
        if to and e.get('date','') > to: continue
        rows.append({
            'Date': e.get('date',''),
            'Department': e.get('department',''),
            'Account': e.get('account',''),
            'Type': e.get('type',''),
            'Subtype': e.get('subtype',''),
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
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and e.get('department','') != dept_f: continue
        if frm and e.get('date','') < frm: continue
        if to and e.get('date','') > to: continue
        rows.append(e)
    rows.sort(key=lambda x: x.get('date',''), reverse=True)
    return render_template('report_pdf.html', data=rows, now=lambda: datetime.now())

# ─── DEBUG ROUTES (safe to remove later) ───────────────────────────────────
@app.route('/debug-entries')
def debug_entries():
    return jsonify(load_json(ENTRIES_FILE, default=list) or [])

@app.route('/debug-budgets')
def debug_budgets():
    return jsonify(load_json(BUDGETS_FILE, default=dict) or {})

# ─── RUN ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=True)
