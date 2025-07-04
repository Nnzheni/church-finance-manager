from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os, io
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","dev")

# point SQLAlchemy at a local file called data.db
app.config["SQLALCHEMY_DATABASE_URI"]   = "sqlite:///data.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ─── FILES ──────────────────────────────────────────────────────────────
USERS_FILE    = 'users.json'
BUDGETS_FILE  = 'budgets.json'
ENTRIES_FILE  = 'entries.json'    # ← Here

# (no more separate INCOME_LOG_FILE or EXPENSE_LOG_FILE)


# ─── FILES ──────────────────────────────────────────────────────────────
USERS_FILE        = 'users.json'
INCOME_LOG_FILE   = 'income_log.json'
EXPENSE_LOG_FILE  = 'expense_log.json'
BUDGETS_FILE      = 'budgets.json'
ENTRIES_FILE      = 'entries.json'    # unified income+expense store

# ─── UTILITIES ──────────────────────────────────────────────────────────
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path,'r') as f:
            return json.load(f)
    return default() if callable(default) else default

def save_json(path, data):
    with open(path,'w') as f:
        json.dump(data, f, indent=2)

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d")

# ─── AUTH ────────────────────────────────────────────────────────────────
@app.route('/', methods=['GET','POST'])
def login():
    if request.method=='POST':
        users = load_json(USERS_FILE, default=dict)
        u = request.form['username']
        p = request.form['password']
        if u in users and users[u]['password']==p:
            session.update({
                'user': u,
                'role': users[u]['role'],
                'dept': users[u]['department']
            })
            return redirect(url_for('dashboard'))
        flash("Invalid credentials","danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─── DASHBOARD ──────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = session['user']
    role = session['role']
    dept = session['dept']
    now  = datetime.now()

    # filters
    acct = request.args.get('account', 'Main')
    m    = int(request.args.get('month', now.month))
    y    = int(request.args.get('year',  now.year))

    # load data
    entries = load_json(ENTRIES_FILE, default=list)
    budgets = load_json(BUDGETS_FILE, default=dict)

    # filter entries by auth/filters
    def keep(e):
        if role=='Finance Manager':
            if acct not in ('Main','Building Fund'): return False
            if e['account'] != acct:               return False
        elif role!='Senior Pastor':
            if e['account'] != dept:                return False
        # Senior Pastor sees all
        d = parse_date(e['date'])
        return d.year==y and d.month==m

    month_entries = [e for e in entries if keep(e)]

    total_inc = sum(e['amount'] for e in month_entries if e['type']=='Income')
    total_exp = sum(e['amount'] for e in month_entries if e['type']=='Expense')
    balance   = total_inc - total_exp
    limit     = budgets.get(acct if role=='Finance Manager' else dept, 0.0)
    remaining = limit - total_exp

    # chart data for the year
    labels     = [f"{y}-{mn:02d}" for mn in range(1,13)]
    def sum_for(lbl, t):
        return sum(e['amount'] for e in entries
                   if e['type']==t
                   and (role=='Senior Pastor'
                        or e['account']==(acct if role=='Finance Manager' else dept))
                   and e['date'].startswith(lbl))
    chart_inc = [sum_for(lbl,'Income')  for lbl in labels]
    chart_exp = [sum_for(lbl,'Expense') for lbl in labels]

    return render_template('dashboard.html',
        user=user, role=role, dept=dept,
        now=now, selected_month=m, selected_year=y,
        current_year=now.year, account=acct,
        total_income=total_inc, total_expense=total_exp,
        balance=balance, budget_limit=limit,
        remaining=remaining,
        chart_labels=labels,
        chart_income=chart_inc,
        chart_expense=chart_exp
    )

# ─── ADD INCOME ────────────────────────────────────────────────────────────
@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session:
        return redirect(url_for('login'))

    role = session['role']
    dept = session['dept']

    # Finance Manager may pick Main/Building; everyone else is locked to their own dept
    if role == 'Finance Manager':
        valid_accounts = ['Main', 'Building Fund']
    elif role == 'Senior Pastor':
        valid_accounts = []            # view-only
    else:
        valid_accounts = [dept]

    if request.method == 'POST':
        # pick or validate account
        if role == 'Finance Manager':
            account = request.form['account']
            if account not in valid_accounts:
                flash('Account not permitted', 'danger')
                return redirect(url_for('add_income'))
        else:
            account = dept

        # build the entry
        entry = {
            'type':        'Income',
            'subtype':     request.form.get('type', '').strip(),
            'account':     account,
            'department':  dept,
            'description': request.form.get('description','').strip(),
            'date':        request.form['date'],
            'amount':      float(request.form['amount'])
        }

        # append to unified entries.json
        entries = load_json(ENTRIES_FILE, default=list)
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)

        flash('Income saved', 'success')
        return redirect(url_for('dashboard'))

    # GET → render form
    return render_template(
        'add_income.html',
        valid_accounts=valid_accounts,
        role=role,
        now=datetime.now()
    )

# ─── ADD EXPENSE ───────────────────────────────────────────────────────────
@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session:
        return redirect(url_for('login'))

    role = session['role']
    dept = session['dept']

    if role == 'Finance Manager':
        valid_accounts = ['Main', 'Building Fund']
    elif role == 'Senior Pastor':
        valid_accounts = []
    else:
        valid_accounts = [dept]

    if request.method == 'POST':
        if role == 'Finance Manager':
            account = request.form['account']
            if account not in valid_accounts:
                flash('Account not permitted', 'danger')
                return redirect(url_for('add_expense'))
        else:
            account = dept

        entry = {
            'type':        'Expense',
            'subtype':     request.form.get('type', '').strip(),
            'account':     account,
            'department':  dept,
            'description': request.form.get('description','').strip(),
            'date':        request.form['date'],
            'amount':      float(request.form['amount'])
        }

        entries = load_json(ENTRIES_FILE, default=list)
        entries.append(entry)
        save_json(ENTRIES_FILE, entries)

        flash('Expense saved', 'success')
        return redirect(url_for('dashboard'))

    return render_template(
        'add_expense.html',
        valid_accounts=valid_accounts,
        role=role,
        now=datetime.now()
    )

# ─── BUDGET MANAGEMENT ───────────────────────────────────────────────────
@app.route('/budgets', methods=['GET','POST'])
def manage_budgets():
    if session.get('role')!='Finance Manager':
        return redirect(url_for('dashboard'))

    budgets = load_json(BUDGETS_FILE, default=dict)
    if request.method=='POST':
        for acc in ['Main','Building Fund']:
            try:
                budgets[acc] = float(request.form.get(acc, budgets.get(acc,0)))
            except ValueError:
                pass
        save_json(BUDGETS_FILE, budgets)
        flash("Budgets updated","success")
        return redirect(url_for('manage_budgets'))

    return render_template('manage_budgets.html', budgets=budgets)

# ─── FINANCE REPORT & EXPORT ─────────────────────────────────────────────────

@app.route('/report')
def report():
    # grab any filters from query-string
    dept_f = request.args.get('department', '')
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    # load everything from the one unified file
    entries = load_json(ENTRIES_FILE, default=list)

    # apply filter logic
    def include(e):
        if dept_f and e['department'] != dept_f:
            return False
        if frm   and e['date'] < frm:
            return False
        if to    and e['date'] > to:
            return False
        return True

    rows = [e for e in entries if include(e)]
    rows.sort(key=lambda e: e['date'], reverse=True)

    return render_template(
      'report.html',
      data=rows,
      department_filter=dept_f,
      from_date=frm,
      to_date=to
    )

# ─── EXPORT EXCEL ─────────────────────────────────────────────────────────
@app.route('/export-excel')
def export_excel():
    # 1) grab filters
    dept_f = request.args.get('department', '').lower()
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    # 2) load & filter
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and dept_f not in e['department'].lower():
            continue
        if frm and e['date'] < frm:
            continue
        if to and e['date'] > to:
            continue

        rows.append({
            'Date':        e['date'],
            'Department':  e['department'],
            'Type':        e['type'],
            'Subtype':     e.get('subtype',''),
            'Description': e.get('description',''),
            'Amount (R)':  e['amount']
        })

    # 3) build DataFrame & Excel
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    output.seek(0)

    # 4) send
    filename = f"report_{dept_f or 'all'}_{frm}_{to}.xlsx"
    return send_file(
        output,
        download_name=filename,
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# ─── EXPORT PDF ───────────────────────────────────────────────────────────
@app.route('/export-pdf')
def export_pdf():
    # same filters
    dept_f = request.args.get('department', '').lower()
    frm    = request.args.get('from_date', '')
    to     = request.args.get('to_date', '')

    # load & filter
    entries = load_json(ENTRIES_FILE, default=list) or []
    rows = []
    for e in entries:
        if dept_f and dept_f not in e['department'].lower():
            continue
        if frm and e['date'] < frm:
            continue
        if to and e['date'] > to:
            continue

        rows.append({
            'date':        e['date'],
            'department':  e['department'],
            'type':        e['type'],
            'subtype':     e.get('subtype',''),
            'description': e.get('description',''),
            'amount':      e['amount']
        })

    rows.sort(key=lambda x: x['date'], reverse=True)

    # render your PDF-friendly template
    return render_template(
        'report_pdf.html',
        data=rows,
        now=datetime.now()
    )

# ─── RUN SERVER ────────────────────────────────────────────────────────────
if __name__=='__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT',10000)),
        debug=True
    )
