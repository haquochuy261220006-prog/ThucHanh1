from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response
from functools import wraps
from datetime import date, datetime, timedelta
import csv, io
import db, auth
from config import CONG_CHUAN, GIO_VAO_CHUAN

app = Flask(__name__)
app.secret_key = 'change-this-to-a-long-random-secret-key'
from contracts import bp as contracts_bp
app.register_blueprint(contracts_bp)

MODULES = {
 'nhanvien': {'title':'Nhân viên','table':'NhanVien','pk':'MaNV','fields':[
  ('HoTen','Họ tên','text',True),('NgaySinh','Ngày sinh','date',False),('GioiTinh','Giới tính','choice:Nam|Nữ|Khác',False),('DiaChi','Địa chỉ','text',False),('SDT','Số điện thoại','text',False),('Email','Email','email',False),('CCCD','CCCD','text',False),('NgayVaoLam','Ngày vào làm','date',False),('MaPB','Phòng ban','department',False),('MaCV','Chức vụ','position',False),('LuongCoBan','Lương cơ bản','number',False),('TrangThai','Trạng thái','choice:Đang làm|Đã nghỉ việc',True)],
  'sql':"SELECT n.MaNV AS [Mã NV],n.HoTen AS [Họ tên],n.NgaySinh AS [Ngày sinh],n.GioiTinh AS [Giới tính],n.SDT AS [SĐT],n.Email,p.TenPB AS [Phòng ban],c.TenCV AS [Chức vụ],n.NgayVaoLam AS [Ngày vào],n.LuongCoBan AS [Lương CB],n.TrangThai AS [Trạng thái] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB LEFT JOIN ChucVu c ON c.MaCV=n.MaCV ORDER BY n.MaNV DESC"},
 'phongban': {'title':'Phòng ban','table':'PhongBan','pk':'MaPB','fields':[('TenPB','Tên phòng ban','text',True),('NguoiPhuTrach','Người phụ trách','text',False),('TrangThai','Trạng thái','choice:Hoạt động|Ngừng hoạt động',True)],'sql':'SELECT MaPB AS [Mã PB],TenPB AS [Tên phòng ban],NguoiPhuTrach AS [Người phụ trách],TrangThai AS [Trạng thái] FROM PhongBan ORDER BY MaPB DESC'},
 'chucvu': {'title':'Chức vụ','table':'ChucVu','pk':'MaCV','fields':[('TenCV','Tên chức vụ','text',True),('MoTa','Mô tả','text',False)],'sql':'SELECT MaCV AS [Mã CV],TenCV AS [Tên chức vụ],MoTa AS [Mô tả] FROM ChucVu ORDER BY MaCV DESC'},
 'hopdong': {'title':'Hợp đồng','table':'HopDong','pk':'MaHD','fields':[('MaNV','Mã nhân viên','number',True),('LoaiHD','Loại hợp đồng','choice:Thử việc|Có thời hạn|Không thời hạn|Thời vụ|Bán thời gian|Học việc|Cộng tác viên|Đào tạo',True),('NgayBatDau','Ngày bắt đầu','date',True),('NgayKetThuc','Ngày kết thúc','date',False),('LuongHD','Lương hợp đồng','number',False),('TrangThai','Trạng thái','choice:Còn hiệu lực|Hết hạn|Đã chấm dứt',True)],'sql':'SELECT h.MaHD AS [Mã HĐ],n.HoTen AS [Nhân viên],h.LoaiHD AS [Loại],h.NgayBatDau AS [Bắt đầu],h.NgayKetThuc AS [Kết thúc],h.LuongHD AS [Lương HĐ],h.TrangThai AS [Trạng thái] FROM HopDong h JOIN NhanVien n ON n.MaNV=h.MaNV ORDER BY h.MaHD DESC'}
}
REPORTS = {
 'Tổng số nhân viên đang làm':("SELECT COUNT(*) AS [Tổng nhân viên] FROM NhanVien WHERE TrangThai=N'Đang làm'",()),
 'Nhân viên theo phòng ban':("SELECT ISNULL(p.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.TrangThai=N'Đang làm' GROUP BY p.TenPB ORDER BY 2 DESC",()),
 'Nhân viên theo chức vụ':("SELECT ISNULL(c.TenCV,N'(Chưa có chức vụ)') AS [Chức vụ],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN ChucVu c ON c.MaCV=n.MaCV WHERE n.TrangThai=N'Đang làm' GROUP BY c.TenCV ORDER BY 2 DESC",()),
 'Nhân viên đã nghỉ việc':("SELECT MaNV AS [Mã NV],HoTen AS [Họ tên],NgayVaoLam AS [Ngày vào làm] FROM NhanVien WHERE TrangThai=N'Đã nghỉ việc'",()),
 'Đơn nghỉ phép theo trạng thái':("SELECT TrangThai AS [Trạng thái],COUNT(*) AS [Số đơn],SUM(SoNgay) AS [Tổng ngày] FROM NghiPhep GROUP BY TrangThai",()),
}
def admin(): return session.get('user',{}).get('role') == 'QuanTri'
def login_required(f):
 @wraps(f)
 def w(*a,**kw):
  if not session.get('user'): return redirect(url_for('login'))
  return f(*a,**kw)
 return w
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  try: u=auth.login(request.form.get('username','').strip(),request.form.get('password',''))
  except Exception as e: flash('Không kết nối được SQL Server. Kiểm tra config.py và dịch vụ SQL Server.','error'); return render_template('login.html')
  if u: session['user']=u; return redirect(url_for('dashboard'))
  flash('Tên đăng nhập hoặc mật khẩu không đúng.','error')
 return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/')
@login_required
def dashboard():
 stats={}
 try:
  stats['staff']=db.scalar("SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm'") or 0
  stats['departments']=db.scalar('SELECT COUNT(*) FROM PhongBan') or 0
  stats['contracts']=db.scalar("SELECT COUNT(*) FROM HopDong WHERE TrangThai=N'Còn hiệu lực'") or 0
  stats['leaves']=db.scalar("SELECT COUNT(*) FROM NghiPhep WHERE TrangThai=N'Chờ duyệt'") or 0
  cols,rows=db.query("SELECT TOP 8 MaNV AS [Mã NV],HoTen AS [Họ tên],Email,TrangThai AS [Trạng thái] FROM NhanVien ORDER BY MaNV DESC")
 except Exception as e: stats['error']=str(e); cols,rows=[],[]
 return render_template('dashboard.html',stats=stats,cols=cols,rows=rows,admin=admin())
def friendly_delete_error(e):
 s=str(e)
 if 'REFERENCE constraint' in s or 'FOREIGN KEY' in s: return 'Không thể xóa vì bản ghi này đang được dùng ở dữ liệu khác (ví dụ phòng ban/chức vụ còn nhân viên). Hãy chuyển hoặc xóa dữ liệu liên quan trước.'
 return s
def delete_record(key,m,id_):
 if key=='nhanvien':
  if str(session['user'].get('manv') or '')==str(id_): raise ValueError('Không thể xóa nhân viên đang gắn với tài khoản bạn đang đăng nhập.')
  # xóa nhân viên cùng toàn bộ dữ liệu liên quan trong 1 giao dịch (lỗi thì hoàn tác hết)
  db.execute("SET NOCOUNT ON; SET XACT_ABORT ON; BEGIN TRAN; DELETE FROM Luong WHERE MaNV=?; DELETE FROM ChamCong WHERE MaNV=?; DELETE FROM NghiPhep WHERE MaNV=?; DELETE FROM HopDong WHERE MaNV=?; DELETE FROM TaiKhoan WHERE MaNV=?; DELETE FROM NhanVien WHERE MaNV=?; COMMIT;",(id_,)*6)
 else: db.execute(f"DELETE FROM {m['table']} WHERE {m['pk']}=?",(id_,))
@app.route('/<key>',methods=['GET','POST'])
@login_required
def module(key):
 if key not in MODULES: return redirect(url_for('dashboard'))
 if not admin() and key in ('nhanvien','phongban','chucvu','hopdong'): flash('Chức năng này dành cho quản trị viên.','error'); return redirect(url_for('dashboard'))
 m=MODULES[key]; edit_id=request.args.get('edit')
 if request.method=='POST':
  action=request.form.get('action'); vals=[]
  try:
   if action in ('add','update'):
    for col,label,typ,req in m['fields']:
     value=request.form.get(col,'').strip()
     if req and not value: raise ValueError('Vui lòng nhập '+label+'.')
     vals.append(value or None)
   if action=='add':
    cols=[f[0] for f in m['fields']]; db.execute(f"INSERT INTO {m['table']} ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",vals); flash('Đã thêm dữ liệu.','success')
   elif action=='update':
    sets=','.join(f"{f[0]}=?" for f in m['fields']); db.execute(f"UPDATE {m['table']} SET {sets} WHERE {m['pk']}=?",vals+[request.form['id']]); flash('Đã cập nhật dữ liệu.','success')
   elif action=='delete': delete_record(key,m,request.form['id']); flash('Đã xóa dữ liệu.','success')
   return redirect(url_for('module',key=key))
  except Exception as e: flash(friendly_delete_error(e) if action=='delete' else str(e),'error')
 edit=None
 if edit_id:
  edit=db.query(f"SELECT {','.join(f[0] for f in m['fields'])} FROM {m['table']} WHERE {m['pk']}=?",(edit_id,))[1]
  edit=dict(zip([f[0] for f in m['fields']],edit[0])) if edit else None
 try:
  cols,rows=db.query(m['sql']); search=request.args.get('q','').strip()
  if search: rows=[r for r in rows if search.casefold() in ' '.join('' if x is None else str(x) for x in r).casefold()]
 except Exception as e: cols,rows=[],[]; flash('Lỗi truy vấn dữ liệu: '+str(e),'error')
 options={}
 if key == 'nhanvien':
  try:
   options['MaPB']=db.query('SELECT MaPB,TenPB FROM PhongBan ORDER BY TenPB')[1]
   options['MaCV']=db.query('SELECT MaCV,TenCV FROM ChucVu ORDER BY TenCV')[1]
  except Exception as e: flash('Không tải được danh sách phòng ban/chức vụ: '+str(e),'error')
 return render_template('module.html',m=m,key=key,cols=cols,rows=rows,edit=edit,edit_id=edit_id,options=options,admin=admin())
@app.route('/chamcong',methods=['GET','POST'])
@login_required
def chamcong():
 today=date.today()
 if request.method=='POST':
  manv=request.form.get('MaNV'); action=request.form.get('action')
  try:
   if action=='delete':
    if not admin(): raise ValueError('Chỉ quản trị viên mới được xóa bản ghi chấm công.')
    db.execute('DELETE FROM ChamCong WHERE MaCC=?',(request.form['id'],)); flash('Đã xóa bản ghi chấm công.','success'); return redirect(url_for('chamcong'))
   exists=db.scalar('SELECT COUNT(*) FROM ChamCong WHERE MaNV=? AND Ngay=?',(manv,today))
   now=datetime.now().strftime('%H:%M:%S')
   if action=='in':
    if exists: db.execute("UPDATE ChamCong SET GioVao=?,TrangThai=? WHERE MaNV=? AND Ngay=?",(now,'Đi muộn' if datetime.now().strftime('%H:%M')>GIO_VAO_CHUAN else 'Đi làm',manv,today))
    else: db.execute("INSERT INTO ChamCong(MaNV,Ngay,GioVao,TrangThai) VALUES(?,?,?,?)",(manv,today,now,'Đi muộn' if datetime.now().strftime('%H:%M')>GIO_VAO_CHUAN else 'Đi làm'))
   else: db.execute('UPDATE ChamCong SET GioRa=? WHERE MaNV=? AND Ngay=?',(now,manv,today))
   flash('Đã ghi nhận chấm công.','success')
  except Exception as e: flash(str(e),'error')
  return redirect(url_for('chamcong'))
 try:
  people=db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
  cols,rows=db.query('SELECT c.MaCC AS [Mã CC],n.HoTen AS [Nhân viên],c.Ngay AS [Ngày],c.GioVao AS [Giờ vào],c.GioRa AS [Giờ ra],c.TrangThai AS [Trạng thái] FROM ChamCong c JOIN NhanVien n ON n.MaNV=c.MaNV WHERE c.Ngay=? ORDER BY c.MaCC DESC',(today,))
 except Exception as e: people=[]; cols,rows=[],[]; flash(str(e),'error')
 return render_template('attendance.html',people=people,cols=cols,rows=rows,today=today,admin=admin())
@app.route('/nghiphep',methods=['GET','POST'])
@login_required
def nghiphep():
 if request.method=='POST':
  try:
   action=request.form.get('action')
   if action=='submit':
    start=date.fromisoformat(request.form['TuNgay']); end=date.fromisoformat(request.form['DenNgay'])
    if end<start: raise ValueError('Ngày kết thúc phải sau ngày bắt đầu.')
    db.execute('INSERT INTO NghiPhep(MaNV,TuNgay,DenNgay,SoNgay,LyDo) VALUES(?,?,?,?,?)',(request.form['MaNV'],start,end,(end-start).days+1,request.form.get('LyDo',''))); flash('Đã gửi đơn nghỉ phép.','success')
   elif action=='approve' and admin(): db.execute('UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?',('Đã duyệt',request.form['id']))
   elif action=='reject' and admin(): db.execute('UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?',('Từ chối',request.form['id']))
   elif action=='delete' and admin(): db.execute('DELETE FROM NghiPhep WHERE MaNP=?',(request.form['id'],)); flash('Đã xóa đơn nghỉ phép.','success')
  except Exception as e: flash(str(e),'error')
  return redirect(url_for('nghiphep'))
 try:
  people=db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
  cols,rows=db.query('SELECT p.MaNP AS [Mã đơn],n.HoTen AS [Nhân viên],p.TuNgay AS [Từ ngày],p.DenNgay AS [Đến ngày],p.SoNgay AS [Số ngày],p.LyDo AS [Lý do],p.TrangThai AS [Trạng thái] FROM NghiPhep p JOIN NhanVien n ON n.MaNV=p.MaNV ORDER BY p.MaNP DESC')
 except Exception as e: people=[]; cols,rows=[],[]; flash(str(e),'error')
 return render_template('leave.html',people=people,cols=cols,rows=rows,admin=admin())
@app.route('/luong',methods=['GET','POST'])
@login_required
def luong():
 if not admin(): return redirect(url_for('dashboard'))
 month=int(request.values.get('month',date.today().month)); year=int(request.values.get('year',date.today().year))
 if request.method=='POST':
  try:
   if request.form.get('action')=='delete':
    db.execute('DELETE FROM Luong WHERE MaLuong=?',(request.form['id'],)); flash('Đã xóa dòng lương.','success'); return redirect(url_for('luong',month=month,year=year))
   db.execute('''MERGE Luong AS t USING (SELECT ? MaNV, ? Thang, ? Nam) s ON t.MaNV=s.MaNV AND t.Thang=s.Thang AND t.Nam=s.Nam WHEN MATCHED THEN UPDATE SET PhuCap=?,KhauTru=?,TongLuong=LuongCB/ ? * NgayCong+?-? WHEN NOT MATCHED THEN INSERT(MaNV,Thang,Nam,NgayCong,LuongCB,PhuCap,KhauTru,TongLuong) SELECT ?,?,?,0,LuongCoBan,?,?,LuongCoBan/ ? * 0+?-? FROM NhanVien WHERE MaNV=?;''',(request.form['MaNV'],month,year,request.form['PhuCap'],request.form['KhauTru'],CONG_CHUAN,request.form['PhuCap'],request.form['KhauTru'],request.form['MaNV'],month,year,request.form['PhuCap'],request.form['KhauTru'],CONG_CHUAN,request.form['PhuCap'],request.form['KhauTru'],request.form['MaNV']))
   flash('Đã cập nhật phụ cấp/khấu trừ.','success')
  except Exception as e: flash(str(e),'error')
  return redirect(url_for('luong',month=month,year=year))
 try:
  people=db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
  cols,rows=db.query('SELECT l.MaLuong AS [Mã],n.HoTen AS [Nhân viên],l.Thang AS [Tháng],l.Nam AS [Năm],l.NgayCong AS [Ngày công],l.LuongCB AS [Lương cơ bản],l.PhuCap AS [Phụ cấp],l.KhauTru AS [Khấu trừ],l.TongLuong AS [Thực lĩnh] FROM Luong l JOIN NhanVien n ON n.MaNV=l.MaNV WHERE l.Thang=? AND l.Nam=? ORDER BY n.HoTen',(month,year))
 except Exception as e: people=[]; cols,rows=[],[]; flash(str(e),'error')
 return render_template('salary.html',people=people,cols=cols,rows=rows,month=month,year=year,admin=admin())
@app.route('/baocao')
@login_required
def baocao():
 if not admin(): return redirect(url_for('dashboard'))
 name=request.args.get('name',list(REPORTS)[0]); sql,params=REPORTS.get(name, next(iter(REPORTS.values())))
 try: cols,rows=db.query(sql,params)
 except Exception as e: cols,rows=[],[]; flash(str(e),'error')
 return render_template('reports.html',names=list(REPORTS),name=name,cols=cols,rows=rows,admin=admin())
@app.route('/export/<key>')
@login_required
def export(key):
 if key not in MODULES: return redirect(url_for('dashboard'))
 cols,rows=db.query(MODULES[key]['sql']); out=io.StringIO(); w=csv.writer(out); w.writerow(cols); w.writerows(rows)
 resp=make_response('\ufeff'+out.getvalue()); resp.headers['Content-Disposition']=f'attachment; filename={key}.csv'; resp.headers['Content-Type']='text/csv; charset=utf-8'; return resp
@app.route('/change-password',methods=['GET','POST'])
@login_required
def change_password():
 if request.method=='POST':
  pw=request.form.get('password','')
  if len(pw)<6: flash('Mật khẩu phải có ít nhất 6 ký tự.','error')
  else:
   try: auth.change_password(session['user']['user'],pw); flash('Đổi mật khẩu thành công.','success'); return redirect(url_for('dashboard'))
   except Exception as e: flash(str(e),'error')
 return render_template('password.html',admin=admin())
if __name__=='__main__': app.run(host='127.0.0.1',port=5000,debug=False)
