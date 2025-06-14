from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import json, os, io
from datetime import datetime
import pandas as pd

# optionally, for Google Sheets integration:
# import gspread
# from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret')

USERS_FILE    = 'users.json'
BUDGETS_FILE  = 'budgets.json'
INCOME_LOG    = 'income_log.json'
EXPENSE_LOG   = 'expense_log.json'

# ---- Helpers ----

def load_json(fn):
    if os.path.exists(fn):
        with open(fn,'r') as f: return json.load(f)
    return []

def save_json(fn, data):
    with open(fn,'w') as f: json.dump(data, f, indent=2)

def load_users():
    return load_json(USERS_FILE)

def load_budgets():
    return load_json(BUDGETS_FILE)

def get_department_budget(dept):
    return load_budgets().get(dept, 0.0)

# optionally, Google Sheets hookup:
# def get_google_sheet(sheet_name):
#     scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
#     creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
#     client = gspread.authorize(creds)
#     return client.open(sheet_name).sheet1

# ---- Routes ----

@app.route('/', methods=['GET','POST'])
def login():
    if request.method=='POST':
        u,p = request.form['username'], request.form['password']
        users = load_users()
        if u in users and users[u]['password']==p:
            session['user'] = u
            session['role'] = users[u]['role']
            session['department'] = users[u]['department']
            return redirect(url_for('dashboard'))
        flash('Invalid credentials','danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))

    dept = session['department']
    role = session['role']

    # pick month/year filters
    now            = datetime.now()
    selected_month = int(request.args.get('month', now.month))
    selected_year  = int(request.args.get('year' , now.year))
    current_year   = now.year

    # load logs
    incomes  = load_json(INCOME_LOG)
    expenses = load_json(EXPENSE_LOG)

    # filter for this dept & month/year
    def in_period(r):
        d = datetime.strptime(r['date'], "%Y-%m-%d")
        return d.month==selected_month and d.year==selected_year

    dept_inc  = [i for i in incomes  if i['department']==dept and in_period(i)]
    dept_exp  = [e for e in expenses if e['department']==dept and in_period(e)]

    total_inc     = sum(i['amount'] for i in dept_inc)
    total_exp     = sum(e['amount'] for e in dept_exp)
    remaining_bdgt = get_department_budget(dept) - total_exp

    # build chart over all 12 months
    chart_labels  = [f"{selected_year}-{m:02d}" for m in range(1,13)]
    chart_income  = [
        sum(i['amount'] for i in incomes if i['department']==dept and i['date'].startswith(lbl))
        for lbl in chart_labels
    ]
    chart_expense = [
        sum(e['amount'] for e in expenses if e['department']==dept and e['date'].startswith(lbl))
        for lbl in chart_labels
    ]

    return render_template('dashboard.html',
        user=session['user'], role=role, dept=dept,
        budget={ 'income': total_inc,
                 'expense': total_exp,
                 'limit':  get_department_budget(dept),
                 'remaining': remaining_bdgt },
        total_income=total_inc, total_expense=total_exp,
        balance=total_inc-total_exp,
        chart_labels=chart_labels,
        chart_income=chart_income,
        chart_expense=chart_expense,
        now=now,
        selected_month=selected_month,
        selected_year=selected_year,
        current_year=current_year
    )

@app.route('/add-income', methods=['GET','POST'])
def add_income():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method=='POST':
        entry = {
            'amount':     float(request.form['amount']),
            'note':       request.form['note'],
            'date':       request.form['date'],
            'department': session['department']
        }
        log = load_json(INCOME_LOG)
        log.append(entry)
        save_json(INCOME_LOG, log)

        # optionally push to Google Sheet:
        # sheet = get_google_sheet("AFM Finance Income")
        # sheet.append_row([entry['date'],entry['department'],entry['note'],entry['amount']])

        flash('Income saved','success')
        return redirect(url_for('dashboard'))
    return render_template('add_income.html')

@app.route('/add-expense', methods=['GET','POST'])
def add_expense():
    if 'user' not in session: return redirect(url_for('login'))
    if request.method=='POST':
        entry = {
            'amount':     float(request.form['amount']),
            'category':   request.form['category'],
            'note':       request.form['note'],
            'date':       request.form['date'],
            'department': session['department']
        }
        log = load_json(EXPENSE_LOG)
        log.append(entry)
        save_json(EXPENSE_LOG, log)

        # optionally push to Google Sheet:
        # sheet = get_google_sheet("AFM Finance Expense")
        # sheet.append_row([entry['date'],entry['department'],entry['category'],entry['amount']])

        flash('Expense saved','success')
        return redirect(url_for('dashboard'))
    return render_template('add_expense.html')

@app.route('/budgets', methods=['GET','POST'])
def manage_budgets():
    if 'user' not in session or session['role']!='Finance Manager':
        return redirect(url_for('login'))
    budgets = load_budgets()
    if request.method=='POST':
        for d in budgets:
            try:
                budgets[d] = float(request.form.get(d, budgets[d]))
            except:
                pass
        save_json(BUDGETS_FILE, budgets)
        flash('Budgets updated','success')
        return redirect(url_for('manage_budgets'))
    return render_template('manage_budgets.html', budgets=budgets)

@app.route('/report')
def report():
    department_filter = request.args.get('department','')
    frm  = request.args.get('from_date','')
    to   = request.args.get('to_date','')

    combined = load_json(INCOME_LOG) + load_json(EXPENSE_LOG)
    for r in combined:
        r['type']        = 'Income'  if 'note' in r else 'Expense'
        r['description'] = r.get('note', r.get('category',''))

    def passes(r):
        if department_filter and department_filter.lower() not in r['department'].lower(): return False
        if frm  and r['date'] < frm: return False
        if to   and r['date'] > to:  return False
        return True

    data = [r for r in combined if passes(r)]
    data.sort(key=lambda r: r['date'], reverse=True)

    return render_template('report.html',
        data=data,
        department_filter=department_filter,
        from_date=frm, to_date=to
    )

@app.route('/export-excel')
def export_excel():
    # mirror report’s filter logic
    department = request.args.get('department','')
    frm        = request.args.get('from_date','')
    to         = request.args.get('to_date','')

    combined = load_json(INCOME_LOG) + load_json(EXPENSE_LOG)
    rows = []
    for r in combined:
        if department and department.lower() not in r['department'].lower(): continue
        if frm  and r['date'] < frm: continue
        if to   and r['date'] > to:  continue
        rows.append({
            'Date':        r['date'],
            'Department':  r['department'],
            'Type':        r['type'],
            'Description': r['description'],
            'Amount (R)':  r['amount']
        })

    df = pd.DataFrame(rows)
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Report')
    out.seek(0)

    filename = f"report_{department or 'all'}_{frm}_{to}.xlsx"
    return send_file(out,
                     download_name=filename,
                     as_attachment=True)

@app.route('/export-pdf')
def export_pdf():
    department = request.args.get('department','')
    frm        = request.args.get('from_date','')
    to         = request.args.get('to_date','')

    combined = load_json(INCOME_LOG) + load_json(EXPENSE_LOG)
    for r in combined:
        r['type']        = 'Income'  if 'note' in r else 'Expense'
        r['description'] = r.get('note', r.get('category',''))

    rows = [r for r in combined
            if (not department or department.lower() in r['department'].lower())
            and (not frm or r['date']>=frm)
            and (not to  or r['date']<=to)]
    rows.sort(key=lambda r: r['date'], reverse=True)

    return render_template('report_pdf.html',
        data=rows, now=lambda: datetime.now()
    )

if __name__=='__main__':
    # if on Render or Heroku you’ll want:
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',10000)), debug=True)
