"""First-run account creation and local launcher."""
import getpass
import secrets
import threading
import webbrowser
import server

def main():
    server.init_db()
    with server.connect() as c:
        exists=c.execute('SELECT 1 FROM users WHERE active=1').fetchone()
    if not exists:
        print('\nCrea tu acceso al panel de Bailes Chinos.\n')
        name=input('Tu nombre: ').strip() or 'Administración'
        email=input('Tu correo: ').strip().lower()
        password=getpass.getpass('Elige una contraseña (mínimo 12 caracteres): ')
        confirmation=getpass.getpass('Repite tu contraseña: ')
        if '@' not in email or not 12<=len(password)<=200 or password!=confirmation:
            raise SystemExit('Revisa el correo y las contraseñas y abre este archivo de nuevo.')
        with server.connect() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',(secrets.token_hex(12),email,name,server.password_hash(password),'admin'))
        print('\nTu cuenta está lista.\n')
    threading.Timer(1,lambda:webbrowser.open('http://127.0.0.1:8000/?admin')).start()
    print('Bailes Chinos está abierto. Mantén esta ventana abierta mientras revisas el sitio.\nPara cerrar el servidor, presiona Control+C.')
    from wsgiref.simple_server import make_server
    with make_server('127.0.0.1',8000,server.app,handler_class=server.QuietHandler) as httpd:
        try:httpd.serve_forever()
        except KeyboardInterrupt:print('\nSitio cerrado. Tus cambios quedaron guardados.')
if __name__=='__main__':main()
