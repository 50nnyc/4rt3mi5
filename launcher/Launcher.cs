// Launcher do 4rt3mi5: o "instalador sem versão".
//
// Por que existe: o SmartScreen do Windows guarda a reputação de um .exe sem assinatura pelo hash do arquivo.
// Cada instalador novo (4rt3mi5-Setup-X.Y.Z.exe) começava do zero e mostrava "O Windows protegeu o computador".
// Este launcher NUNCA muda (os bytes ficam congelados em launcher\4rt3mi5-Launcher.exe), então a reputação dele
// só cresce. Ele lê o latest.json da última Release, baixa o instalador da versão nova, confere o SHA-256 e
// instala em silêncio. Arquivos baixados pelo próprio programa não passam pelo aviso do SmartScreen.
//
// Regras de segurança (iguais às do atualizador do app, artemis/desktop/updater.py):
//  - manifesto e instalador só das Releases de github.com/50nnyc/4rt3mi5, sempre por HTTPS;
//  - redirecionamentos só para os servidores de download do GitHub;
//  - o instalador só roda se o SHA-256 bater com o do manifesto.
//
// Compilado por launcher\build-launcher.ps1 com o csc do .NET Framework 4 (vem em todo Windows 10/11).
// Por isso é C# 5: nada de $"...", ?. ou nameof.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("4rt3mi5")]
[assembly: AssemblyDescription("4rt3mi5 - instala e abre o companheiro de hunt")]
[assembly: AssemblyProduct("4rt3mi5")]
[assembly: AssemblyCompany("4rt3mi5")]
[assembly: AssemblyCopyright("4rt3mi5 - github.com/50nnyc/4rt3mi5")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace Artemis
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new LauncherForm());
        }
    }

    class Manifest
    {
        public string Version, Url, Sha256;
    }

    class LauncherForm : Form
    {
        // ---------------------------------------------------------------- constantes
        const string LauncherVersion = "1.0";
        const string ManifestUrl = "https://github.com/50nnyc/4rt3mi5/releases/latest/download/latest.json";
        const string TrustedPrefix = "https://github.com/50nnyc/4rt3mi5/releases/";
        static readonly string[] TrustedHosts = { "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com" };
        const string SiteUrl = "https://artemis-hunt.duckdns.org";
        const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\{B3E1F7A2-58C4-4D9E-A1F0-7C2D4E6B9A35}_is1";
        const int W = 860, H = 520;  // tamanho lógico; a tela real é multiplicada pela escala do Windows

        static readonly Color Gold = Color.FromArgb(242, 201, 76);
        static readonly Color Gold2 = Color.FromArgb(255, 241, 193);
        static readonly Color GoldDark = Color.FromArgb(168, 122, 18);
        static readonly Color TextC = Color.FromArgb(233, 236, 242);
        static readonly Color Muted = Color.FromArgb(160, 168, 190);
        static readonly Color Bad = Color.FromArgb(255, 122, 107);

        // ---------------------------------------------------------------- estado
        enum St { Checking, Install, Update, Ready, Offline, NoNet, Downloading, Installing, Error }
        St state = St.Checking;
        string status = "Procurando a versão mais nova…";
        bool statusBad;
        double progress;
        Manifest latest;
        string installedVersion, appExe;

        Bitmap art, scaledArt;
        float scale = 1f;
        RectangleF btnRect = new RectangleF(510, 214, 260, 58);
        RectangleF closeRect = new RectangleF(818, 10, 32, 28);
        RectangleF minRect = new RectangleF(782, 10, 32, 28);
        RectangleF siteRect;
        string hover = "";
        bool pressed;
        float pulse;
        readonly System.Windows.Forms.Timer anim = new System.Windows.Forms.Timer();
        readonly List<Spark> sparks = new List<Spark>();
        readonly Random rnd = new Random(7);

        class Spark { public float X, Y, R, Speed, Phase; }

        public LauncherForm()
        {
            Text = "4rt3mi5";
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(5, 6, 13);
            DoubleBuffered = true;
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint, true);
            KeyPreview = true;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            using (Graphics g = Graphics.FromHwnd(IntPtr.Zero)) scale = Math.Max(1f, g.DpiX / 96f);
            ClientSize = new Size((int)Math.Round(W * scale), (int)Math.Round(H * scale));

            Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("fundo.png");
            if (s != null) using (s) art = new Bitmap(s);
            BuildScaledArt();

            for (int i = 0; i < 26; i++)
                sparks.Add(new Spark { X = 80 + (float)rnd.NextDouble() * 760, Y = 140 + (float)rnd.NextDouble() * 380,
                    R = 0.6f + (float)rnd.NextDouble() * 1.4f, Speed = 0.12f + (float)rnd.NextDouble() * 0.28f,
                    Phase = (float)(rnd.NextDouble() * Math.PI * 2) });
            anim.Interval = 40;
            anim.Tick += delegate { pulse += 0.04f; MoveSparks(); Invalidate(); };
            anim.Start();

            ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;  // TLS 1.2
            Shown += delegate { RoundCorners(); StartCheck(); };
            KeyDown += delegate(object o, KeyEventArgs e) {
                if (e.KeyCode == Keys.Escape && state != St.Downloading && state != St.Installing) Close();
                if (e.KeyCode == Keys.Enter) MainAction();
            };
        }

        // janela sem borda: sombra do sistema e cantos arredondados no Windows 11
        protected override CreateParams CreateParams
        {
            get { CreateParams cp = base.CreateParams; cp.ClassStyle |= 0x20000; return cp; }  // CS_DROPSHADOW
        }

        [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int val, int size);
        [DllImport("user32.dll")] static extern bool ReleaseCapture();
        [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);

        void RoundCorners()
        {
            try { int pref = 2; DwmSetWindowAttribute(Handle, 33, ref pref, 4); } catch { }
        }

        void BuildScaledArt()
        {
            if (art == null) return;
            scaledArt = new Bitmap(ClientSize.Width, ClientSize.Height, PixelFormat.Format32bppPArgb);
            using (Graphics g = Graphics.FromImage(scaledArt))
            {
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                g.DrawImage(art, new Rectangle(0, 0, scaledArt.Width, scaledArt.Height));
            }
        }

        void MoveSparks()
        {
            foreach (Spark p in sparks)
            {
                p.Y -= p.Speed; p.X += (float)Math.Sin(pulse + p.Phase) * 0.15f;
                if (p.Y < 120) { p.Y = 520; p.X = 80 + (float)rnd.NextDouble() * 760; }
            }
        }

        // ---------------------------------------------------------------- versão instalada
        void ReadInstalled()
        {
            installedVersion = null; appExe = null;
            foreach (RegistryKey root in new[] { Registry.CurrentUser, Registry.LocalMachine })
            {
                try
                {
                    using (RegistryKey k = root.OpenSubKey(UninstallKey))
                    {
                        if (k == null) continue;
                        string v = k.GetValue("DisplayVersion") as string;
                        string dir = k.GetValue("InstallLocation") as string;
                        if (!string.IsNullOrEmpty(dir))
                        {
                            string exe = Path.Combine(dir.Trim('"'), "4rt3mi5.exe");
                            if (File.Exists(exe)) { installedVersion = v; appExe = exe; return; }
                        }
                    }
                }
                catch { }
            }
            string fallback = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), @"Programs\4rt3mi5\4rt3mi5.exe");
            if (File.Exists(fallback)) { appExe = fallback; installedVersion = installedVersion ?? "0"; }
        }

        static int[] VTuple(string v)
        {
            List<int> r = new List<int>();
            foreach (string p in (v ?? "").Trim().TrimStart('v').Split('.')) { int n; if (int.TryParse(p, out n)) r.Add(n); }
            return r.ToArray();
        }

        static bool Newer(string a, string b)  // a > b ?
        {
            int[] x = VTuple(a), y = VTuple(b);
            for (int i = 0; i < Math.Max(x.Length, y.Length); i++)
            {
                int p = i < x.Length ? x[i] : 0, q = i < y.Length ? y[i] : 0;
                if (p != q) return p > q;
            }
            return false;
        }

        // ---------------------------------------------------------------- rede (só GitHub, só HTTPS)
        static bool Trusted(string url)
        {
            return url != null && url.StartsWith(TrustedPrefix, StringComparison.Ordinal) && !url.Contains("..");
        }

        static HttpWebResponse Open(string url, int timeoutMs)
        {
            for (int hop = 0; hop < 6; hop++)
            {
                Uri u = new Uri(url);
                if (u.Scheme != "https" || Array.IndexOf(TrustedHosts, u.Host.ToLowerInvariant()) < 0)
                    throw new Exception("Download bloqueado: servidor não confiável (" + u.Host + ").");
                HttpWebRequest req = (HttpWebRequest)WebRequest.Create(u);
                req.AllowAutoRedirect = false;
                req.UserAgent = "4rt3mi5-launcher/" + LauncherVersion;
                req.Timeout = timeoutMs; req.ReadWriteTimeout = timeoutMs;
                req.Headers["Cache-Control"] = "no-cache";
                HttpWebResponse resp;
                try { resp = (HttpWebResponse)req.GetResponse(); }
                catch (WebException we)
                {
                    resp = we.Response as HttpWebResponse;
                    if (resp == null) throw;
                }
                int code = (int)resp.StatusCode;
                if (code >= 300 && code < 400)
                {
                    string loc = resp.Headers["Location"]; resp.Close();
                    if (string.IsNullOrEmpty(loc)) throw new Exception("Redirecionamento sem destino.");
                    url = new Uri(u, loc).ToString();
                    continue;
                }
                if (code != 200) { resp.Close(); throw new Exception("O GitHub respondeu " + code + "."); }
                return resp;
            }
            throw new Exception("Redirecionamentos demais.");
        }

        static Manifest FetchManifest()
        {
            string raw;
            using (HttpWebResponse r = Open(ManifestUrl, 15000))
            using (Stream s = r.GetResponseStream())
            {
                byte[] buf = new byte[64 * 1024]; int total = 0, n;
                while (total < buf.Length && (n = s.Read(buf, total, buf.Length - total)) > 0) total += n;
                raw = Encoding.UTF8.GetString(buf, 0, total).TrimStart('﻿');
            }
            Manifest m = new Manifest { Version = Field(raw, "version"), Url = Field(raw, "url"), Sha256 = (Field(raw, "sha256") ?? "").ToLowerInvariant() };
            if (m.Version == null || !Regex.IsMatch(m.Version, @"^\d+(\.\d+){1,3}$")) throw new Exception("Manifesto inválido (versão).");
            if (!Regex.IsMatch(m.Sha256, "^[0-9a-f]{64}$")) throw new Exception("Manifesto inválido (SHA-256).");
            if (!Trusted(m.Url) || !m.Url.EndsWith(".exe", StringComparison.OrdinalIgnoreCase)) throw new Exception("Instalador fora das Releases oficiais.");
            return m;
        }

        static string Field(string json, string name)
        {
            Match mt = Regex.Match(json, "\"" + name + "\"\\s*:\\s*\"([^\"\\\\]*)\"");
            return mt.Success ? mt.Groups[1].Value : null;
        }

        // ---------------------------------------------------------------- fluxo
        void StartCheck()
        {
            SetState(St.Checking, "Procurando a versão mais nova…", false);
            ThreadPool.QueueUserWorkItem(delegate
            {
                ReadInstalled();
                Manifest m = null; Exception err = null;
                try { m = FetchManifest(); } catch (Exception e) { err = e; }
                BeginInvoke((MethodInvoker)delegate
                {
                    latest = m;
                    if (m == null)
                    {
                        if (appExe != null) SetState(St.Offline, "Sem conexão com o GitHub. Dá para abrir a versão instalada.", false);
                        else SetState(St.NoNet, "Sem conexão. Confira a internet e tente de novo." + Detail(err), true);
                    }
                    else if (appExe == null) SetState(St.Install, "Primeira vez? Vamos instalar a versão " + m.Version + " no seu PC.", false);
                    else if (Newer(m.Version, installedVersion)) SetState(St.Update, "Versão " + m.Version + " disponível (você tem a " + installedVersion + ").", false);
                    else SetState(St.Ready, "Versão " + installedVersion + " instalada · tudo em dia.", false);
                });
            });
        }

        static string Detail(Exception e)
        {
            return e == null || e is WebException ? "" : " (" + e.Message + ")";
        }

        void SetState(St s, string msg, bool bad)
        {
            state = s; status = msg; statusBad = bad; Invalidate();
        }

        string ButtonLabel()
        {
            switch (state)
            {
                case St.Checking: return "AGUARDE…";
                case St.Install: return "INSTALAR";
                case St.Update: return "ATUALIZAR";
                case St.Ready: case St.Offline: return "ENTRAR";
                case St.NoNet: case St.Error: return "TENTAR DE NOVO";
                case St.Downloading: return "BAIXANDO " + (int)(progress * 100) + "%";
                case St.Installing: return "INSTALANDO…";
            }
            return "";
        }

        bool ButtonEnabled()
        {
            return state != St.Checking && state != St.Downloading && state != St.Installing;
        }

        void MainAction()
        {
            if (!ButtonEnabled()) return;
            switch (state)
            {
                case St.Install: case St.Update: Download(); break;
                case St.Ready: case St.Offline: OpenApp(); break;
                default: StartCheck(); break;
            }
        }

        void OpenApp()
        {
            try
            {
                Process.Start(new ProcessStartInfo(appExe) { WorkingDirectory = Path.GetDirectoryName(appExe), UseShellExecute = true });
                Close();
            }
            catch (Exception e) { SetState(St.Error, "Não consegui abrir o 4rt3mi5: " + e.Message, true); }
        }

        void Download()
        {
            Manifest m = latest;
            progress = 0;
            SetState(St.Downloading, "Baixando a versão " + m.Version + " do GitHub…", false);
            ThreadPool.QueueUserWorkItem(delegate
            {
                string dir = null;
                try
                {
                    dir = Path.Combine(Path.GetTempPath(), "4rt3mi5-launcher-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                    Directory.CreateDirectory(dir);
                    string file = Path.Combine(dir, "4rt3mi5-Setup-" + m.Version + ".exe");
                    using (SHA256 sha = SHA256.Create())
                    using (HttpWebResponse r = Open(m.Url, 60000))
                    using (Stream s = r.GetResponseStream())
                    using (FileStream f = new FileStream(file, FileMode.CreateNew, FileAccess.Write))
                    {
                        long total = r.ContentLength, done = 0; byte[] buf = new byte[256 * 1024]; int n;
                        while ((n = s.Read(buf, 0, buf.Length)) > 0)
                        {
                            f.Write(buf, 0, n); sha.TransformBlock(buf, 0, n, null, 0); done += n;
                            if (total > 0) { double p = (double)done / total; BeginInvoke((MethodInvoker)delegate { progress = p; Invalidate(); }); }
                        }
                        sha.TransformFinalBlock(new byte[0], 0, 0);
                        string got = BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
                        if (got != m.Sha256) throw new Exception("o arquivo baixado não confere (SHA-256 diferente). Nada foi instalado.");
                    }
                    BeginInvoke((MethodInvoker)delegate { SetState(St.Installing, "Instalando… o 4rt3mi5 abre sozinho no final.", false); });
                    // /VERYSILENT: sem telas. O próprio instalador abre o app quando termina.
                    using (Process p = Process.Start(new ProcessStartInfo(file, "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS") { UseShellExecute = false }))
                    {
                        p.WaitForExit();
                        if (p.ExitCode != 0) throw new Exception("o instalador terminou com o código " + p.ExitCode + ".");
                    }
                    BeginInvoke((MethodInvoker)delegate { Close(); });
                }
                catch (Exception e)
                {
                    string msg = e is WebException ? "a conexão caiu durante o download." : e.Message;
                    BeginInvoke((MethodInvoker)delegate { SetState(St.Error, "Não deu certo: " + msg, true); });
                }
                finally
                {
                    try { if (dir != null) Directory.Delete(dir, true); } catch { }
                }
            });
        }

        // ---------------------------------------------------------------- mouse
        PointF Logical(Point p) { return new PointF(p.X / scale, p.Y / scale); }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            PointF p = Logical(e.Location);
            string h = btnRect.Contains(p) && ButtonEnabled() ? "btn" : closeRect.Contains(p) ? "close" : minRect.Contains(p) ? "min"
                : siteRect.Contains(p) ? "site" : "";
            if (h != hover) { hover = h; Cursor = h == "" ? Cursors.Default : Cursors.Hand; Invalidate(); }
        }

        protected override void OnMouseLeave(EventArgs e) { hover = ""; pressed = false; Invalidate(); }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            if (hover == "") { ReleaseCapture(); SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero); return; }  // arrastar a janela
            pressed = hover == "btn"; Invalidate();
        }

        protected override void OnMouseUp(MouseEventArgs e)
        {
            if (e.Button != MouseButtons.Left) return;
            pressed = false;
            if (hover == "btn") MainAction();
            else if (hover == "close") { if (state != St.Downloading && state != St.Installing) Close(); }
            else if (hover == "min") WindowState = FormWindowState.Minimized;
            else if (hover == "site") { try { Process.Start(new ProcessStartInfo(SiteUrl) { UseShellExecute = true }); } catch { } }
            Invalidate();
        }

        // ---------------------------------------------------------------- desenho
        static GraphicsPath Round(RectangleF r, float rad)
        {
            GraphicsPath g = new GraphicsPath(); float d = rad * 2;
            g.AddArc(r.X, r.Y, d, d, 180, 90); g.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            g.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90); g.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            g.CloseFigure(); return g;
        }

        static void Shadowed(Graphics g, string s, Font f, Color c, RectangleF r, StringFormat sf)
        {
            using (SolidBrush sh = new SolidBrush(Color.FromArgb(170, 0, 0, 0)))
                g.DrawString(s, f, sh, new RectangleF(r.X + 1, r.Y + 1.2f, r.Width, r.Height), sf);
            using (SolidBrush b = new SolidBrush(c)) g.DrawString(s, f, b, r, sf);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            if (scaledArt != null) g.DrawImageUnscaled(scaledArt, 0, 0); else g.Clear(BackColor);
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            g.ScaleTransform(scale, scale);

            // faíscas douradas subindo
            foreach (Spark p in sparks)
            {
                int a = (int)(60 + 110 * (0.5 + 0.5 * Math.Sin(pulse * 2 + p.Phase)));
                using (SolidBrush glow = new SolidBrush(Color.FromArgb(a / 4, 255, 215, 122))) g.FillEllipse(glow, p.X - p.R * 2.5f, p.Y - p.R * 2.5f, p.R * 5, p.R * 5);
                using (SolidBrush dot = new SolidBrush(Color.FromArgb(a, 255, 225, 150))) g.FillEllipse(dot, p.X - p.R, p.Y - p.R, p.R * 2, p.R * 2);
            }

            StringFormat center = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center };

            // botão principal
            bool en = ButtonEnabled();
            RectangleF b = btnRect;
            if (pressed) b.Offset(0, 1.5f);
            if (en)
            {
                float glowA = (state == St.Ready || state == St.Install || state == St.Update) ? (float)(0.5 + 0.5 * Math.Sin(pulse * 1.6)) : 0.3f;
                for (int i = 4; i >= 1; i--)
                {
                    RectangleF gr = RectangleF.Inflate(b, i * 3.5f, i * 3.5f);
                    using (GraphicsPath gp = Round(gr, 14 + i * 3))
                    using (SolidBrush gb = new SolidBrush(Color.FromArgb((int)((hover == "btn" ? 34 : 18 + 16 * glowA) / i), Gold)))
                        g.FillPath(gb, gp);
                }
            }
            using (GraphicsPath path = Round(b, 12))
            {
                Color top = en ? (hover == "btn" ? Color.FromArgb(255, 248, 214) : Gold2) : Color.FromArgb(60, 58, 70);
                Color mid = en ? (hover == "btn" ? Color.FromArgb(250, 214, 96) : Gold) : Color.FromArgb(42, 40, 52);
                Color bot = en ? GoldDark : Color.FromArgb(28, 27, 36);
                using (LinearGradientBrush lg = new LinearGradientBrush(b, top, bot, LinearGradientMode.Vertical))
                {
                    ColorBlend cb = new ColorBlend(3);
                    cb.Colors = new[] { top, mid, bot }; cb.Positions = new[] { 0f, 0.45f, 1f };
                    lg.InterpolationColors = cb;
                    g.FillPath(lg, path);
                }
                // reflexo de cima
                RectangleF hl = new RectangleF(b.X + 3, b.Y + 2, b.Width - 6, b.Height * 0.42f);
                using (GraphicsPath hp = Round(hl, 10))
                using (LinearGradientBrush hb = new LinearGradientBrush(hl, Color.FromArgb(en ? 90 : 25, 255, 255, 255), Color.FromArgb(0, 255, 255, 255), LinearGradientMode.Vertical))
                    g.FillPath(hb, hp);
                using (Pen pen = new Pen(en ? Color.FromArgb(200, 122, 88, 10) : Color.FromArgb(120, Gold), 1.2f)) g.DrawPath(pen, path);
            }
            // barra de progresso dentro do botão
            if (state == St.Downloading && progress > 0)
            {
                RectangleF pr = new RectangleF(b.X + 10, b.Bottom - 9, (b.Width - 20) * (float)Math.Min(1, progress), 3.5f);
                using (SolidBrush tb = new SolidBrush(Color.FromArgb(70, 255, 255, 255))) g.FillRectangle(tb, b.X + 10, b.Bottom - 9, b.Width - 20, 3.5f);
                using (SolidBrush pb = new SolidBrush(Gold)) g.FillRectangle(pb, pr);
            }
            using (Font bf = new Font("Palatino Linotype", 17f, FontStyle.Bold, GraphicsUnit.Pixel))
            using (Font bfBig = new Font("Palatino Linotype", 21f, FontStyle.Bold, GraphicsUnit.Pixel))
            {
                string label = ButtonLabel();
                Font f = label.Length <= 9 ? bfBig : bf;
                Color tc = en ? Color.FromArgb(38, 26, 2) : Gold;
                using (SolidBrush lb = new SolidBrush(en ? Color.FromArgb(110, 255, 246, 214) : Color.FromArgb(150, 0, 0, 0)))
                    g.DrawString(Spaced(label), f, lb, new RectangleF(b.X, b.Y + 1, b.Width, b.Height - (state == St.Downloading ? 4 : 0)), center);
                using (SolidBrush tb2 = new SolidBrush(tc))
                    g.DrawString(Spaced(label), f, tb2, new RectangleF(b.X, b.Y, b.Width, b.Height - (state == St.Downloading ? 4 : 0)), center);
            }

            // texto de situação
            using (Font sf = new Font("Segoe UI", 12.5f, FontStyle.Regular, GraphicsUnit.Pixel))
            {
                RectangleF sr = new RectangleF(btnRect.X - 70, btnRect.Bottom + 12, btnRect.Width + 140, 40);
                StringFormat top = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Near };
                Shadowed(g, status, sf, statusBad ? Bad : TextC, sr, top);
            }

            // rodapé: versão do launcher e o site
            using (Font ff = new Font("Segoe UI", 11.5f, FontStyle.Regular, GraphicsUnit.Pixel))
            using (Font fu = new Font("Segoe UI", 11.5f, FontStyle.Underline, GraphicsUnit.Pixel))
            {
                string left = "Launcher " + LauncherVersion + (installedVersion != null && installedVersion != "0" ? "  ·  app " + installedVersion : "");
                Shadowed(g, left, ff, Muted, new RectangleF(18, H - 30, 400, 20), new StringFormat());
                string site = "artemis-hunt.duckdns.org  ↗";
                SizeF sz = g.MeasureString(site, ff);
                siteRect = new RectangleF(W - 18 - sz.Width, H - 30, sz.Width, 20);
                Shadowed(g, site, hover == "site" ? fu : ff, hover == "site" ? Gold : Muted, siteRect, new StringFormat());
            }

            // minimizar e fechar
            DrawWinButton(g, minRect, hover == "min", false);
            DrawWinButton(g, closeRect, hover == "close", true);

            // borda fina dourada
            using (Pen bp = new Pen(Color.FromArgb(70, Gold), 1f)) g.DrawRectangle(bp, 0.5f, 0.5f, W - 1, H - 1);
        }

        static string Spaced(string s)
        {
            StringBuilder sb = new StringBuilder();
            foreach (char c in s) { if (sb.Length > 0) sb.Append(' '); sb.Append(c); }
            return sb.ToString();
        }

        static void DrawWinButton(Graphics g, RectangleF r, bool hot, bool close)
        {
            if (hot)
                using (GraphicsPath p = Round(r, 6))
                using (SolidBrush b = new SolidBrush(close ? Color.FromArgb(200, 196, 43, 28) : Color.FromArgb(60, 255, 255, 255))) g.FillPath(b, p);
            float cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2;
            using (Pen pen = new Pen(hot ? Color.White : Color.FromArgb(200, 233, 236, 242), 1.4f))
            {
                if (close) { g.DrawLine(pen, cx - 5, cy - 5, cx + 5, cy + 5); g.DrawLine(pen, cx + 5, cy - 5, cx - 5, cy + 5); }
                else g.DrawLine(pen, cx - 5.5f, cy, cx + 5.5f, cy);
            }
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if ((state == St.Downloading || state == St.Installing) && e.CloseReason == CloseReason.UserClosing && !closingAllowed)
            {
                e.Cancel = true; return;
            }
            anim.Stop();
            base.OnFormClosing(e);
        }
        bool closingAllowed;

        protected override void OnFormClosed(FormClosedEventArgs e)
        {
            base.OnFormClosed(e);
        }

        public new void Close()
        {
            closingAllowed = true; base.Close();
        }
    }
}
