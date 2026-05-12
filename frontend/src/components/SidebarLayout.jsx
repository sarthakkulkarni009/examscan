import { useState, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getNotifications, markAllNotificationsRead } from '../api/moderation';
import './SidebarLayout.css';

function SidebarLayout({ children }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const [showNotifDropdown, setShowNotifDropdown] = useState(false);

  useEffect(() => {
    if (user?.role === 'teacher' || user?.role === 'exam_dept') {
      loadNotifications();
      const interval = setInterval(loadNotifications, 60000);
      return () => clearInterval(interval);
    }
  }, [user?.role]);

  const loadNotifications = async () => {
    try {
      const res = await getNotifications();
      setNotifications(res.data.results || res.data || []);
    } catch { /* silent */ }
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllNotificationsRead();
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
    } catch { /* silent */ }
  };

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  const unreadCount = notifications.filter(n => !n.is_read).length;

  // Define navigation based on user role
  const getNavLinks = () => {
    const role = user?.role || '';
    if (role === 'exam_dept') {
      return [
        { label: 'Dashboard', path: '/exam/dashboard', icon: '🎛️' },
        { label: 'Users', path: '/exam/users', icon: '👥' },
        { label: 'Assign Teachers', path: '/exam/assign', icon: '🧑‍🏫' },
        { label: 'Subjects & Schemes', path: '/exam/schemes', icon: '📚' },
        { label: 'Token Manager', path: '/exam/tokens', icon: '🏷️' },
        { label: 'Reports', path: '/exam/reports', icon: '📊' },
      ];
    } else if (role === 'scanning_staff') {
      return [
        { label: 'New Bundle', path: '/scanning/session', icon: '📦' },
        ...(!location.pathname.includes('/scanning/session') && location.pathname.includes('/scanning') 
            ? [{ label: 'Scanner Tools', path: location.pathname, icon: '🖨️' }] : [])
      ];
    } else if (role === 'teacher') {
      return [
        { label: 'Dashboard', path: '/teacher/dashboard', icon: '🎛️' },
      ];
    }
    return [];
  };

  const navLinks = getNavLinks();

  // Helper to format role nicely
  const formatRole = (roleStr) => {
    if (!roleStr) return '';
    return roleStr.replace('_', ' ').toUpperCase();
  };

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        {/* Logo Area */}
        <div className="sidebar-header">
          <div className="logo">
            <span className="logo-icon">🎓</span> 
            <span className="logo-text">ExamFlow</span>
          </div>
        </div>

        {/* Navigation Area */}
        <nav className="sidebar-nav">
          {navLinks.map((link) => {
            const isActive = location.pathname.startsWith(link.path);
            return (
              <Link
                key={link.path}
                to={link.path}
                className={`nav-item ${isActive ? 'active' : ''}`}
              >
                <span className="nav-icon">{link.icon}</span>
                <span className="nav-label">{link.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Notification bell */}
        {(user?.role === 'teacher' || user?.role === 'exam_dept') && (
          <div className="sidebar-notifications">
            <button
              className="notif-bell-btn"
              onClick={() => setShowNotifDropdown(!showNotifDropdown)}
            >
              🔔
              {unreadCount > 0 && <span className="notif-badge">{unreadCount}</span>}
            </button>
            {showNotifDropdown && (
              <div className="notif-dropdown">
                <div className="notif-dropdown-header">
                  <span style={{ fontWeight: 600 }}>Notifications</span>
                  {unreadCount > 0 && (
                    <button className="btn btn-ghost btn-sm" onClick={handleMarkAllRead} style={{ fontSize: '0.75rem' }}>
                      Mark all read
                    </button>
                  )}
                </div>
                <div className="notif-dropdown-list">
                  {notifications.length === 0 ? (
                    <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                      No notifications
                    </div>
                  ) : notifications.slice(0, 10).map(n => (
                    <div key={n.id} className={`notif-item ${n.is_read ? '' : 'notif-unread'}`}>
                      <div className="notif-message">{n.message}</div>
                      <div className="notif-time">{new Date(n.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* User Profile Area */}
        <div className="sidebar-footer">
          <div className="user-meta">
            <span className="user-role">{formatRole(user?.role)}</span>
            <span className="user-name">{user?.fullName || user?.username || 'User'}</span>
          </div>
          <button className="sign-out-btn" onClick={handleLogout}>
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        {children}
      </main>
    </div>
  );
}

export default SidebarLayout;
