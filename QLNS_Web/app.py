from flask import Flask, render_template, request, redirect, url_for, session, flash, make_response, jsonify
from functools import wraps
from datetime import date, datetime, timedelta
import csv, io, re, unicodedata
import db, auth
import config
from config import CONG_CHUAN, GIO_VAO_CHUAN
from payroll import tinh_luong

app = Flask(__name__)
app.secret_key = 'change-this-to-a-long-random-secret-key'
from contracts import bp as contracts_bp
app.register_blueprint(contracts_bp)

MODULES = {
 'nhanvien': {'title':'Nhân viên','table':'NhanVien','pk':'MaNV','fields':[
  ('HoTen','Họ tên','text',True),('NgaySinh','Ngày sinh','date',False),('GioiTinh','Giới tính','choice:Nam|Nữ|Khác',False),('DiaChi','Địa chỉ','text',False),('SDT','Số điện thoại','text',False),('Email','Email','email',False),('CCCD','CCCD','text',False),('NgayVaoLam','Ngày vào làm','date',False),('MaPB','Phòng ban','department',False),('MaCV','Chức vụ','position',False),('LuongCoBan','Lương cơ bản','number',False),('TrangThai','Trạng thái','choice:Đang làm|Đã nghỉ việc',True)],
  'sql':"SELECT n.MaNV AS [_id],ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))) AS [Mã NV],n.HoTen AS [Họ tên],n.NgaySinh AS [Ngày sinh],n.GioiTinh AS [Giới tính],n.SDT AS [SĐT],n.Email,p.TenPB AS [Phòng ban],c.TenCV AS [Chức vụ],n.NgayVaoLam AS [Ngày vào],n.LuongCoBan AS [Lương CB],n.TrangThai AS [Trạng thái] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB LEFT JOIN ChucVu c ON c.MaCV=n.MaCV ORDER BY n.MaNV DESC"},
 'phongban': {'title':'Phòng ban','table':'PhongBan','pk':'MaPB','fields':[('TenPB','Tên phòng ban','text',True),('KyHieu','Ký hiệu (VD: KT)','text',True),('NguoiPhuTrach','Người phụ trách','text',False),('TrangThai','Trạng thái','choice:Hoạt động|Ngừng hoạt động',True)],'sql':'SELECT MaPB AS [Mã PB],TenPB AS [Tên phòng ban],KyHieu AS [Ký hiệu],NguoiPhuTrach AS [Người phụ trách],TrangThai AS [Trạng thái] FROM PhongBan ORDER BY MaPB DESC'},
 'chucvu': {'title':'Chức vụ','table':'ChucVu','pk':'MaCV','fields':[('TenCV','Tên chức vụ','text',True),('MoTa','Mô tả','text',False)],'sql':'SELECT MaCV AS [Mã CV],TenCV AS [Tên chức vụ],MoTa AS [Mô tả] FROM ChucVu ORDER BY MaCV DESC'},
 'hopdong': {'title':'Hợp đồng','table':'HopDong','pk':'MaHD','fields':[('MaNV','Nhân viên','employee',True),('LoaiHD','Loại hợp đồng','choice:Thử việc|Có thời hạn|Không thời hạn|Thời vụ|Bán thời gian|Học việc|Cộng tác viên|Đào tạo',True),('NgayBatDau','Ngày bắt đầu','date',True),('NgayKetThuc','Ngày kết thúc','date',False),('LuongHD','Lương hợp đồng','number',False),('TrangThai','Trạng thái','choice:Còn hiệu lực|Hết hạn|Đã chấm dứt',True)],'sql':'SELECT h.MaHD AS [Mã HĐ],n.HoTen AS [Nhân viên],h.LoaiHD AS [Loại],h.NgayBatDau AS [Bắt đầu],h.NgayKetThuc AS [Kết thúc],h.LuongHD AS [Lương HĐ],h.TrangThai AS [Trạng thái] FROM HopDong h JOIN NhanVien n ON n.MaNV=h.MaNV ORDER BY h.MaHD DESC'}
}
REPORTS = {
 'Tổng số nhân viên đang làm':("SELECT COUNT(*) AS [Tổng nhân viên] FROM NhanVien WHERE TrangThai=N'Đang làm'",()),
 'Nhân viên theo phòng ban':("SELECT ISNULL(p.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.TrangThai=N'Đang làm' GROUP BY p.TenPB ORDER BY 2 DESC",()),
 'Nhân viên theo chức vụ':("SELECT ISNULL(c.TenCV,N'(Chưa có chức vụ)') AS [Chức vụ],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN ChucVu c ON c.MaCV=n.MaCV WHERE n.TrangThai=N'Đang làm' GROUP BY c.TenCV ORDER BY 2 DESC",()),
 'Nhân viên đã nghỉ việc':("SELECT ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) AS [Mã NV],HoTen AS [Họ tên],NgayVaoLam AS [Ngày vào làm] FROM NhanVien WHERE TrangThai=N'Đã nghỉ việc'",()),
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
 if not admin(): return redirect(url_for('chamcong'))
 stats={}
 try:
  stats['staff']=db.scalar("SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm'") or 0
  stats['departments']=db.scalar('SELECT COUNT(*) FROM PhongBan') or 0
  stats['contracts']=db.scalar("SELECT COUNT(*) FROM HopDong WHERE TrangThai=N'Còn hiệu lực'") or 0
  stats['leaves']=db.scalar("SELECT COUNT(*) FROM NghiPhep WHERE TrangThai=N'Chờ duyệt'") or 0
  cols,rows=db.query("SELECT TOP 8 ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) AS [Mã NV],HoTen AS [Họ tên],Email,TrangThai AS [Trạng thái] FROM NhanVien ORDER BY MaNV DESC")
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
_KY_MAC_DINH={'nhan su':'NS','ke toan':'KTO','kinh doanh':'KD','ky thuat':'KT','marketing':'MKT'}
def _bo_dau(t):
 t=unicodedata.normalize('NFD',t.replace('đ','d').replace('Đ','D'))
 return ''.join(ch for ch in t if unicodedata.category(ch)!='Mn')
def assign_codes():
 """Cấp Mã NV hiển thị = NV + số thứ tự chung 2 chữ số + ký hiệu phòng ở cuối (NV01KT, NV02NS...)."""
 rows=db.query('SELECT n.MaNV,p.KyHieu FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.MaNVHT IS NULL ORDER BY n.MaNV')[1]
 if not rows: return
 mx=0
 for (code,) in db.query('SELECT MaNVHT FROM NhanVien WHERE MaNVHT IS NOT NULL')[1]:
  m=re.fullmatch(r'NV(\d+)[A-Z]*',code or '')
  if m: mx=max(mx,int(m.group(1)))
 for manv,ky in rows:
  mx+=1; db.execute('UPDATE NhanVien SET MaNVHT=? WHERE MaNV=?',('NV%02d%s'%(mx,(ky or '').upper()),manv))
def ensure_schema():
 db.execute("IF COL_LENGTH('PhongBan','KyHieu') IS NULL ALTER TABLE PhongBan ADD KyHieu NVARCHAR(10) NULL")
 db.execute("IF COL_LENGTH('NhanVien','MaNVHT') IS NULL ALTER TABLE NhanVien ADD MaNVHT NVARCHAR(20) NULL")
 for col,typ in [('ThuongCC','DECIMAL(18,0)'),('GioTangCa','DECIMAL(7,2)'),('TienTangCa','DECIMAL(18,0)'),('SoLanMuon','INT'),('TruMuon','DECIMAL(18,0)'),('SoNgayNghiKP','INT'),('TruNghiKP','DECIMAL(18,0)')]:
  db.execute(f"IF COL_LENGTH('Luong','{col}') IS NULL ALTER TABLE Luong ADD {col} {typ} NOT NULL DEFAULT 0")
 pbs=db.query('SELECT MaPB,TenPB,KyHieu FROM PhongBan ORDER BY MaPB')[1]
 used={r[2] for r in pbs if r[2]}
 for mapb,ten,ky in pbs:
  if ky: continue
  base=_bo_dau(re.sub(r'(?i)^(phòng|ban)\s+','',ten.strip())).lower()
  cand=_KY_MAC_DINH.get(base) or ''.join(w[0] for w in base.split() if w[:1].isalpha()).upper()[:5] or 'PB'
  cand=re.sub('[^A-Z]','',cand.upper()) or 'PB'; k=cand; i=2
  while k in used: k=cand[:4]+chr(64+i); i+=1
  used.add(k); db.execute('UPDATE PhongBan SET KyHieu=? WHERE MaPB=?',(k,mapb))
 # đổi từ định dạng mã cũ (vd KT01) sang định dạng mới: cấp lại toàn bộ 1 lần
 if db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNVHT IS NOT NULL AND MaNVHT NOT LIKE 'NV[0-9]%'"): db.execute('UPDATE NhanVien SET MaNVHT=NULL')
 assign_codes()
 db.execute("IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_PhongBan_KyHieu') CREATE UNIQUE INDEX UX_PhongBan_KyHieu ON PhongBan(KyHieu) WHERE KyHieu IS NOT NULL")
 db.execute("IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_NhanVien_MaNVHT') CREATE UNIQUE INDEX UX_NhanVien_MaNVHT ON NhanVien(MaNVHT) WHERE MaNVHT IS NOT NULL")
_schema_ok=False
@app.before_request
def _auto_schema():
 global _schema_ok
 if _schema_ok or request.endpoint in (None,'static','login'): return
 try: ensure_schema(); _schema_ok=True
 except Exception as e: print('ensure_schema lỗi:',e)
def ensure_pbcv():
 db.execute("IF OBJECT_ID('PhongBan_ChucVu','U') IS NULL CREATE TABLE PhongBan_ChucVu(MaPB INT NOT NULL REFERENCES PhongBan(MaPB) ON DELETE CASCADE, MaCV INT NOT NULL REFERENCES ChucVu(MaCV) ON DELETE CASCADE, PRIMARY KEY(MaPB,MaCV))")
@app.route('/api/chucvu-nhanh',methods=['POST'])
@login_required
def chucvu_nhanh():
 if not admin(): return jsonify(ok=False,error='Chức năng này dành cho quản trị viên.'),403
 data=request.get_json(silent=True) or {}; ten=(data.get('TenCV') or '').strip()
 try:
  if not ten: raise ValueError('Vui lòng nhập tên chức vụ.')
  if len(ten)>100: raise ValueError('Tên chức vụ tối đa 100 ký tự.')
  try: mapb=int(data.get('MaPB'))
  except (TypeError,ValueError): raise ValueError('Vui lòng chọn phòng ban trước.')
  if not db.scalar('SELECT COUNT(*) FROM PhongBan WHERE MaPB=?',(mapb,)): raise ValueError('Phòng ban không tồn tại.')
  ensure_pbcv()
  row=db.query('SELECT MaCV,TenCV FROM ChucVu WHERE TenCV=?',(ten,))[1]
  if not row:
   db.execute('INSERT INTO ChucVu(TenCV) VALUES(?)',(ten,)); row=db.query('SELECT MaCV,TenCV FROM ChucVu WHERE TenCV=?',(ten,))[1]
   db.execute('INSERT INTO PhongBan_ChucVu(MaPB,MaCV) VALUES(?,?)',(mapb,row[0][0]))
  else:
   macv=row[0][0]
   # chức vụ chung (chưa gắn phòng nào) đã dùng được cho mọi phòng -> không gắn thêm để khỏi làm mất ở phòng khác
   if db.scalar('SELECT COUNT(*) FROM PhongBan_ChucVu WHERE MaCV=?',(macv,)) and not db.scalar('SELECT COUNT(*) FROM PhongBan_ChucVu WHERE MaPB=? AND MaCV=?',(mapb,macv)):
    db.execute('INSERT INTO PhongBan_ChucVu(MaPB,MaCV) VALUES(?,?)',(mapb,macv))
  return jsonify(ok=True,id=row[0][0],name=row[0][1])
 except Exception as e: return jsonify(ok=False,error=str(e)),400
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
     if col=='KyHieu':
      value=value.upper()
      if not re.fullmatch('[A-Z]{1,5}',value): raise ValueError('Ký hiệu phòng ban gồm 1-5 chữ cái không dấu, ví dụ KT.')
      if db.scalar('SELECT COUNT(*) FROM PhongBan WHERE KyHieu=? AND MaPB<>?',(value,request.form.get('id') or -1)): raise ValueError('Ký hiệu '+value+' đã được phòng ban khác dùng.')
     if req and not value: raise ValueError('Vui lòng nhập '+label+'.')
     vals.append(value or None)
   if action=='add':
    cols=[f[0] for f in m['fields']]; db.execute(f"INSERT INTO {m['table']} ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",vals); 
    if key=='nhanvien': assign_codes()
    flash('Đã thêm dữ liệu.','success')
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
  if search:
   if key=='nhanvien': q_=search.casefold(); rows=[r for r in rows if q_ in (str(r[1]).casefold(),re.sub('[a-z]+$','',str(r[1]).casefold()))]  # tìm nhanh nhân viên: chỉ theo Mã NV
   else: rows=[r for r in rows if search.casefold() in ' '.join('' if x is None else str(x) for x in r).casefold()]
 except Exception as e: cols,rows=[],[]; flash('Lỗi truy vấn dữ liệu: '+str(e),'error')
 options={}
 if key == 'nhanvien':
  try:
   options['MaPB']=db.query('SELECT MaPB,TenPB FROM PhongBan ORDER BY TenPB')[1]
   options['MaCV']=db.query('SELECT MaCV,TenCV FROM ChucVu ORDER BY TenCV')[1]
   ensure_pbcv()
   links=db.query('SELECT MaPB,MaCV FROM PhongBan_ChucVu')[1]; dm={}
   for pb_,cv_ in links: dm.setdefault(cv_,[]).append(pb_)
   options['cv_data']=[{'id':c[0],'name':c[1],'depts':dm.get(c[0],[])} for c in options['MaCV']]
  except Exception as e: flash('Không tải được danh sách phòng ban/chức vụ: '+str(e),'error')
 if key=='hopdong':
  try: options['MaNV']=[[r[0],(r[2] or str(r[0]))+' - '+r[1]] for r in db.query('SELECT MaNV,HoTen,MaNVHT FROM NhanVien ORDER BY HoTen')[1]]
  except Exception as e: flash('Không tải được danh sách nhân viên: '+str(e),'error')
 return render_template('module.html',m=m,key=key,cols=cols,rows=rows,edit=edit,edit_id=edit_id,options=options,admin=admin())
@app.route('/chamcong',methods=['GET','POST'])
@login_required
def chamcong():
 today=date.today()
 if request.method=='POST':
  manv=request.form.get('MaNV') if admin() else session['user'].get('manv'); action=request.form.get('action')
  try:
   if action in ('in','out') and not manv: raise ValueError('Tài khoản chưa gắn với nhân viên nào, hãy liên hệ quản trị viên.')
   if action=='delete':
    if not admin(): raise ValueError('Chỉ quản trị viên mới được xóa bản ghi chấm công.')
    db.execute('DELETE FROM ChamCong WHERE MaCC=?',(request.form['id'],)); flash('Đã xóa bản ghi chấm công.','success'); return redirect(url_for('chamcong'))
   exists=db.scalar('SELECT COUNT(*) FROM ChamCong WHERE MaNV=? AND Ngay=?',(manv,today))
   now=datetime.now().strftime('%H:%M:%S')
   if action=='in':
    if exists: db.execute("UPDATE ChamCong SET GioVao=?,TrangThai=? WHERE MaNV=? AND Ngay=?",(now,'Đi muộn' if datetime.now().strftime('%H:%M')>GIO_VAO_CHUAN else 'Đi làm',manv,today))
    else: db.execute("INSERT INTO ChamCong(MaNV,Ngay,GioVao,TrangThai) VALUES(?,?,?,?)",(manv,today,now,'Đi muộn' if datetime.now().strftime('%H:%M')>GIO_VAO_CHUAN else 'Đi làm'))
   else:
    if not db.execute('UPDATE ChamCong SET GioRa=? WHERE MaNV=? AND Ngay=?',(now,manv,today)): raise ValueError('Hôm nay chưa có giờ vào, hãy chấm vào trước khi chấm ra.')
   flash('Đã ghi nhận chấm công.','success')
  except Exception as e: flash(str(e),'error')
  return redirect(url_for('chamcong'))
 flt='' if admin() else ' AND MaNV=%d'%int(session['user'].get('manv') or -1)
 try:
  people=db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm'"+flt+" ORDER BY HoTen")[1]
  cols,rows=db.query('SELECT c.MaCC AS [Mã CC],n.HoTen AS [Nhân viên],c.Ngay AS [Ngày],c.GioVao AS [Giờ vào],c.GioRa AS [Giờ ra],c.TrangThai AS [Trạng thái] FROM ChamCong c JOIN NhanVien n ON n.MaNV=c.MaNV WHERE c.Ngay=?'+flt.replace('MaNV','c.MaNV')+' ORDER BY c.MaCC DESC',(today,))
 except Exception as e: people=[]; cols,rows=[],[]; flash(str(e),'error')
 return render_template('attendance.html',people=people,cols=cols,rows=rows,today=today,admin=admin())
@app.route('/nghiphep',methods=['GET','POST'])
@login_required
def nghiphep():
 if request.method=='POST':
  try:
   action=request.form.get('action')
   if action=='submit':
    manv_=request.form.get('MaNV') if admin() else session['user'].get('manv')
    if not manv_: raise ValueError('Tài khoản chưa gắn với nhân viên nào, hãy liên hệ quản trị viên.')
    start=date.fromisoformat(request.form['TuNgay']); end=date.fromisoformat(request.form['DenNgay'])
    if end<start: raise ValueError('Ngày kết thúc phải sau ngày bắt đầu.')
    db.execute('INSERT INTO NghiPhep(MaNV,TuNgay,DenNgay,SoNgay,LyDo) VALUES(?,?,?,?,?)',(manv_,start,end,(end-start).days+1,request.form.get('LyDo',''))); flash('Đã gửi đơn nghỉ phép.','success')
   elif action=='approve' and admin(): db.execute('UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?',('Đã duyệt',request.form['id'])); flash('Đã duyệt đơn nghỉ phép.','success')
   elif action=='reject' and admin(): db.execute('UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?',('Từ chối',request.form['id'])); flash('Đã không duyệt đơn nghỉ phép.','success')
   elif action=='delete' and admin(): db.execute('DELETE FROM NghiPhep WHERE MaNP=?',(request.form['id'],)); flash('Đã xóa đơn nghỉ phép.','success')
  except Exception as e: flash(str(e),'error')
  return redirect(url_for('nghiphep'))
 flt='' if admin() else ' AND MaNV=%d'%int(session['user'].get('manv') or -1)
 try:
  people=db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm'"+flt+" ORDER BY HoTen")[1]
  cols,rows=db.query('SELECT p.MaNP AS [Mã đơn],n.HoTen AS [Nhân viên],p.TuNgay AS [Từ ngày],p.DenNgay AS [Đến ngày],p.SoNgay AS [Số ngày],p.LyDo AS [Lý do],p.TrangThai AS [Trạng thái] FROM NghiPhep p JOIN NhanVien n ON n.MaNV=p.MaNV'+(' WHERE 1=1'+flt.replace('MaNV','p.MaNV') if flt else '')+' ORDER BY p.MaNP DESC')
 except Exception as e: people=[]; cols,rows=[],[]; flash(str(e),'error')
 return render_template('leave.html',people=people,cols=cols,rows=rows,admin=admin())
@app.route('/luong',methods=['GET','POST'])
@login_required
def luong():
 if not admin(): return redirect(url_for('dashboard'))
 month=int(request.values.get('month',date.today().month)); year=int(request.values.get('year',date.today().year))
 if request.method=='POST':
  try:
   action=request.form.get('action')
   if action=='delete':
    db.execute('DELETE FROM Luong WHERE MaLuong=?',(request.form['id'],))
    flash('Đã xóa dòng lương.','success')
   elif action=='calculate':
    today=date.today()
    if (year,month)>(today.year,today.month): raise ValueError('Chưa thể tính lương cho tháng trong tương lai.')
    first=date(year,month,1); last=date(year+(month==12),month%12+1,1)-timedelta(days=1)
    people=db.query("SELECT MaNV,LuongCoBan,NgayVaoLam FROM NhanVien WHERE TrangThai=N'Đang làm'")[1]
    cc={}; nghi={}
    for r in db.query('SELECT MaNV,Ngay,GioVao,GioRa,TrangThai FROM ChamCong WHERE Ngay>=? AND Ngay<=?',(first,last))[1]: cc.setdefault(r[0],[]).append(r[1:])
    for r in db.query("SELECT MaNV,TuNgay,DenNgay FROM NghiPhep WHERE TrangThai=N'Đã duyệt' AND TuNgay<=? AND DenNgay>=?",(last,first))[1]: nghi.setdefault(r[0],[]).append(r[1:])
    for manv,luong_cb,ngay_vao in people:
     r=tinh_luong(luong_cb,ngay_vao,cc.get(manv,[]),nghi.get(manv,[]),year,month,today)
     vals=(r['ngay_di_lam'],luong_cb or 0,r['phu_cap'],r['khau_tru'],r['tong'],r['thuong_cc'],r['gio_tang_ca'],r['tien_tang_ca'],r['so_lan_muon'],r['tru_muon'],r['so_ngay_nghi_kp'],r['tru_nghi_kp'])
     n=db.execute('UPDATE Luong SET NgayCong=?,LuongCB=?,PhuCap=?,KhauTru=?,TongLuong=?,ThuongCC=?,GioTangCa=?,TienTangCa=?,SoLanMuon=?,TruMuon=?,SoNgayNghiKP=?,TruNghiKP=? WHERE MaNV=? AND Thang=? AND Nam=?',vals+(manv,month,year))
     if not n: db.execute('INSERT INTO Luong(NgayCong,LuongCB,PhuCap,KhauTru,TongLuong,ThuongCC,GioTangCa,TienTangCa,SoLanMuon,TruMuon,SoNgayNghiKP,TruNghiKP,MaNV,Thang,Nam) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',vals+(manv,month,year))
    flash(f'Đã tính lương tháng {month}/{year} cho {len(people)} nhân viên.'+(' Tháng chưa kết thúc: ngày nghỉ không phép chỉ tính đến hôm qua.' if last>=today else ''),'success')
   return redirect(url_for('luong',month=month,year=year))
  except Exception as e: flash('Không thể xử lý bảng lương: '+str(e),'error')
  return redirect(url_for('luong',month=month,year=year))
 try:
  cols,rows=db.query('''SELECT l.MaLuong AS [Mã],n.HoTen AS [Nhân viên],l.NgayCong AS [Ngày đi làm],l.LuongCB AS [Lương cơ bản],
    CAST(ROUND(l.LuongCB / CAST(? AS DECIMAL(10,2)),0) AS DECIMAL(18,0)) AS [Lương/ngày],l.ThuongCC AS [Thưởng chuyên cần],
    CAST(CAST(l.GioTangCa AS DECIMAL(7,1)) AS VARCHAR(10)) AS [Giờ tăng ca],l.TienTangCa AS [Tiền tăng ca],
    l.SoLanMuon AS [Số lần muộn],l.TruMuon AS [Trừ đi muộn],l.SoNgayNghiKP AS [Ngày nghỉ KP],l.TruNghiKP AS [Trừ nghỉ KP],
    l.TongLuong AS [Thực lĩnh] FROM Luong l JOIN NhanVien n ON n.MaNV=l.MaNV
    WHERE l.Thang=? AND l.Nam=? ORDER BY n.HoTen''',(CONG_CHUAN,month,year))
 except Exception as e: cols,rows=[],[]; flash(str(e),'error')
 return render_template('salary.html',cols=cols,rows=rows,month=month,year=year,standard=CONG_CHUAN,cfg=config,admin=admin())

@app.route('/dieuchuyen',methods=['GET','POST'])
@login_required
def dieuchuyen():
 if not admin(): return redirect(url_for('dashboard'))
 try:
  db.execute("""IF OBJECT_ID('LichSuDieuChuyen','U') IS NULL
    CREATE TABLE LichSuDieuChuyen(
      MaDieuChuyen INT IDENTITY(1,1) PRIMARY KEY,
      MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
      MaPB_Cu INT NULL REFERENCES PhongBan(MaPB),
      MaPB_Moi INT NOT NULL REFERENCES PhongBan(MaPB),
      ThoiDiemChuyen DATETIME2(0) NOT NULL,
      LyDo NVARCHAR(500) NULL,
      NguoiThucHien NVARCHAR(100) NULL)""")
 except Exception as e: flash('Không tạo được bảng lịch sử điều chuyển: '+str(e),'error')
 if request.method=='POST':
  try:
   manv=int(request.form['MaNV']); pb_moi=int(request.form['MaPB_Moi'])
   thoi_diem=datetime.fromisoformat(request.form['ThoiDiemChuyen'])
   current=db.query('SELECT MaPB FROM NhanVien WHERE MaNV=?',(manv,))[1]
   if not current: raise ValueError('Không tìm thấy nhân viên.')
   pb_cu=current[0][0]
   if pb_cu is not None and int(pb_cu)==pb_moi: raise ValueError('Nhân viên hiện đã thuộc phòng ban này.')
   if not db.scalar("SELECT COUNT(*) FROM PhongBan WHERE MaPB=? AND TrangThai=N'Hoạt động'",(pb_moi,)):
    raise ValueError('Phòng ban mới không tồn tại hoặc đã ngừng hoạt động.')
   db.execute("""SET XACT_ABORT ON; BEGIN TRAN;
      INSERT INTO LichSuDieuChuyen(MaNV,MaPB_Cu,MaPB_Moi,ThoiDiemChuyen,LyDo,NguoiThucHien)
      VALUES(?,?,?,?,?,?);
      UPDATE NhanVien SET MaPB=? WHERE MaNV=?;
      COMMIT;""",(manv,pb_cu,pb_moi,thoi_diem,request.form.get('LyDo','').strip() or None,session['user']['user'],pb_moi,manv))
   flash('Đã điều chuyển nhân viên và lưu ngày giờ chuyển.','success')
  except Exception as e: flash('Điều chuyển thất bại: '+str(e),'error')
  return redirect(url_for('dieuchuyen'))
 try:
  people=db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
  departments=db.query("SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB")[1]
  cols,rows=db.query('''SELECT ls.MaDieuChuyen AS [Mã],n.HoTen AS [Nhân viên],
    ISNULL(cu.TenPB,N'(Chưa phân phòng)') AS [Phòng ban cũ],moi.TenPB AS [Phòng ban mới],
    ls.ThoiDiemChuyen AS [Ngày giờ chuyển],ls.LyDo AS [Lý do],ls.NguoiThucHien AS [Người thực hiện]
    FROM LichSuDieuChuyen ls JOIN NhanVien n ON n.MaNV=ls.MaNV
    LEFT JOIN PhongBan cu ON cu.MaPB=ls.MaPB_Cu JOIN PhongBan moi ON moi.MaPB=ls.MaPB_Moi
    ORDER BY ls.ThoiDiemChuyen DESC''')
 except Exception as e: people=[]; departments=[]; cols,rows=[],[]; flash('Không tải được lịch sử điều chuyển: '+str(e),'error')
 return render_template('transfer.html',people=people,departments=departments,cols=cols,rows=rows,admin=admin())

@app.route('/baocao')
@login_required
def baocao():
 if not admin(): return redirect(url_for('dashboard'))
 name=request.args.get('name',list(REPORTS)[0]); sql,params=REPORTS.get(name, next(iter(REPORTS.values())))
 try: cols,rows=db.query(sql,params)
 except Exception as e: cols,rows=[],[]; flash(str(e),'error')
 return render_template('reports.html',names=list(REPORTS),name=name,cols=cols,rows=rows,admin=admin())
@app.route('/taikhoan',methods=['GET','POST'])
@login_required
def taikhoan():
 if not admin(): return redirect(url_for('dashboard'))
 if request.method=='POST':
  try:
   action=request.form.get('action')
   if action=='add':
    u=request.form.get('username','').strip(); pw=request.form.get('password',''); manv=request.form.get('MaNV')
    if not manv: raise ValueError('Vui lòng chọn nhân viên.')
    if not re.fullmatch(r'[A-Za-z0-9_.]{3,30}',u): raise ValueError('Tên đăng nhập gồm 3-30 ký tự: chữ không dấu, số, dấu chấm hoặc gạch dưới.')
    if len(pw)<6: raise ValueError('Mật khẩu phải có ít nhất 6 ký tự.')
    if db.scalar('SELECT COUNT(*) FROM TaiKhoan WHERE TenDN=?',(u,)): raise ValueError('Tên đăng nhập đã tồn tại.')
    if db.scalar('SELECT COUNT(*) FROM TaiKhoan WHERE MaNV=?',(manv,)): raise ValueError('Nhân viên này đã có tài khoản.')
    if not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'",(manv,)): raise ValueError('Nhân viên không tồn tại hoặc đã nghỉ việc.')
    auth.create_account(u,pw,'NhanVien',int(manv)); flash('Đã tạo tài khoản '+u+' (chỉ chấm công và gửi đơn nghỉ phép).','success')
   elif action=='delete':
    u=request.form.get('username','')
    if u==session['user']['user']: raise ValueError('Không thể xóa tài khoản đang đăng nhập.')
    db.execute("DELETE FROM TaiKhoan WHERE TenDN=? AND VaiTro=N'NhanVien'",(u,)); flash('Đã xóa tài khoản.','success')
  except Exception as e: flash(str(e),'error')
  return redirect(url_for('taikhoan'))
 try:
  people=db.query("SELECT n.MaNV,n.HoTen,ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))) FROM NhanVien n WHERE n.TrangThai=N'Đang làm' AND NOT EXISTS (SELECT 1 FROM TaiKhoan t WHERE t.MaNV=n.MaNV) ORDER BY n.HoTen")[1]
  cols,rows=db.query("SELECT t.TenDN AS [Tên đăng nhập],CASE t.VaiTro WHEN N'QuanTri' THEN N'Quản trị viên' ELSE N'Nhân viên (chấm công, nghỉ phép)' END AS [Quyền],ISNULL(n.HoTen,N'—') AS [Nhân viên],ISNULL(n.MaNVHT,N'—') AS [Mã NV] FROM TaiKhoan t LEFT JOIN NhanVien n ON n.MaNV=t.MaNV ORDER BY t.VaiTro,t.TenDN")
 except Exception as e: people=[]; cols,rows=[],[]; flash(str(e),'error')
 return render_template('taikhoan.html',people=people,cols=cols,rows=rows,admin=admin())
@app.route('/export/<key>')
@login_required
def export(key):
 if not admin() or key not in MODULES: return redirect(url_for('dashboard'))
 cols,rows=db.query(MODULES[key]['sql'])
 if key=='nhanvien': cols=cols[1:]; rows=[r[1:] for r in rows]
 out=io.StringIO(); w=csv.writer(out); w.writerow(cols); w.writerows(rows)
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
