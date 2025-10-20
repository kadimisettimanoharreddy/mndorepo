import { useState, useEffect } from 'react';
import {
  Box,
  Drawer,
  AppBar,
  Toolbar,
  List,
  Typography,
  Divider,
  IconButton,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Avatar,
  Chip,
  Badge,
  useTheme,
  useMediaQuery,
  Button,
  Menu,
  MenuItem,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Snackbar,
  Alert,
} from '@mui/material';
import {
  Menu as MenuIcon,
  Dashboard,
  Chat,
  Settings,
  CloudQueue,
  ArrowBack,
  Notifications,
  NotificationsActive,
  Clear,
  VolumeUp,
  ExpandMore,
  Launch,
  MonitorHeart
} from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { notificationAPI } from '../../services/api';

const drawerWidth = 280;

interface LayoutProps {
  children: React.ReactNode;
}

interface StoredNotification {
  id: string;
  title: string;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
  timestamp: Date;
  read: boolean;
  deployment_details?: any;
}

export default function Layout({ children }: LayoutProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [notificationCount, setNotificationCount] = useState(0);
  const [notificationAnchor, setNotificationAnchor] = useState<null | HTMLElement>(null);
  const [storedNotifications, setStoredNotifications] = useState<StoredNotification[]>([]);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [expandedNotifications, setExpandedNotifications] = useState<Set<string>>(new Set());
  const [realTimeUpdates, setRealTimeUpdates] = useState(true);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState('');
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error' | 'info' | 'warning'>('info');
  
  const { user, logout, loading } = useAuth();

  // Debug user data
  useEffect(() => {
    console.log('Layout - User data:', user);
  }, [user]);
  const { ws } = useWebSocket();
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  // Token persists across page refreshes - only cleared on explicit logout

  useEffect(() => {
    console.log('Layout - checking auth, user:', user);
    // Only redirect if we're sure there's no user (not loading)
    if (!user && !loading) {
      console.log('Layout - redirecting to login');
      navigate('/login');
    }
  }, [user, navigate]);

  const menuItems = [
    { text: 'Dashboard', icon: <Dashboard />, path: '/' },
    { text: 'Chat Assistant', icon: <Chat />, path: '/chat' },
    { text: 'Monitoring', icon: <MonitorHeart />, path: '/monitoring' },
    { text: 'Settings', icon: <Settings />, path: '/settings' },
  ];

  useEffect(() => {
    loadStoredNotifications();
    fetchOfflineNotifications();
    
    // Listen for storage changes to sync notifications across tabs
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'layout_notifications') {
        loadStoredNotifications();
        playNotificationSound();
      }
    };
    
    // Real-time polling for notifications
    let pollInterval: NodeJS.Timeout;
    let pollDelay = 30000; // 30 seconds for real-time updates (reduced frequency)
    
    const startPolling = () => {
      pollInterval = setInterval(() => {
        if (realTimeUpdates && document.visibilityState === 'visible') {
          fetchOfflineNotifications();
          // HTTP fallback popup is handled in fetchOfflineNotifications
        }
      }, pollDelay);
    };
    
    startPolling();
    
    // Listen to WebSocket for real-time notifications
    const handleWebSocketMessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      
      // Simple duplicate prevention without useRef
      const messageId = data.message_id || `${data.type}_${data.timestamp || Date.now()}`;
      
      // Handle popup notifications (temporary snackbar ONLY)
      if (data.type === 'popup_notification') {
        const popup = data.popup;
        console.log('🚨 POPUP RECEIVED:', popup.title, messageId);
        
        setSnackbarMessage(popup.message);
        setSnackbarSeverity(popup.type || 'info');
        setSnackbarOpen(true);
        
        console.log('✅ POPUP DISPLAYED:', popup.title, '- Message:', popup.message);
        
        // Play sound if enabled
        if (soundEnabled) {
          playNotificationSound();
        }
        
        // Send delivery confirmation
        if (ws) {
          ws.send(JSON.stringify({
            type: 'popup_delivered',
            popup_id: popup.id,
            message_id: messageId,
            timestamp: Date.now()
          }));
        }
      }
      
      // Handle bell notifications (persistent) - auto-update
      else if (data.type === 'notification') {
        console.log('🔔 NOTIFICATION RECEIVED:', data.title, messageId);
        
        const bellNotification = {
          id: `bell_${messageId}`,
          title: data.title,
          message: data.message.replace(/PR #\d+/g, 'Pull Request'),
          type: data.notification_type === 'success' ? 'success' : 
                data.notification_type === 'error' ? 'error' : 'info',
          timestamp: new Date(),
          read: false,
          deployment_details: data.data || {}
        };
        
        // Enhanced duplicate prevention with unique ID tracking
        setStoredNotifications(prev => {
          // Check for duplicates using multiple criteria
          const isDuplicate = prev.some(n => {
            // Same title and message within 10 seconds
            const sameContent = n.title === bellNotification.title && n.message === bellNotification.message;
            const recentTime = Math.abs(new Date(n.timestamp).getTime() - bellNotification.timestamp.getTime()) < 10000;
            
            // Same notification ID (if available)
            const sameId = messageId && n.id.includes(messageId.split('_')[1]);
            
            return (sameContent && recentTime) || sameId;
          });
          
          if (isDuplicate) {
            console.log('🚫 Duplicate bell notification blocked:', bellNotification.title, messageId);
            return prev;
          }
          
          const updated = [bellNotification, ...prev].slice(0, 15);
          const unreadCount = updated.filter(n => !n.read).length;
          setNotificationCount(unreadCount);
          
          // Save to localStorage
          localStorage.setItem('layout_notifications', JSON.stringify(updated));
          console.log('✅ BELL DELIVERED:', bellNotification.title, '- Count updated');
          return updated;
        });
      }
      
      // Handle real-time request updates
      else if (data.type === 'request_update') {
        console.log('📊 Request update received:', data.request.request_identifier);
        
        // Trigger dashboard update with new data
        window.dispatchEvent(new CustomEvent('requestUpdate', { detail: data.request }));
      }
    };
    
    if (ws) {
      ws.addEventListener('message', handleWebSocketMessage);
    }
    
    window.addEventListener('storage', handleStorageChange);
    return () => {
      window.removeEventListener('storage', handleStorageChange);
      clearInterval(pollInterval);
      if (ws) {
        ws.removeEventListener('message', handleWebSocketMessage);
      }
      // Cleanup handled by component unmount
    };
  }, [user, realTimeUpdates, ws]);

  const loadStoredNotifications = () => {
    try {
      const stored = localStorage.getItem('layout_notifications');
      if (stored) {
        const parsed = JSON.parse(stored).map((n: any) => ({
          ...n,
          timestamp: new Date(n.timestamp)
        }));
        setStoredNotifications(parsed);
        updateNotificationCount(parsed);
      }
    } catch (error) {
      console.error('Error loading stored notifications');
      // Initialize with empty array on error
      setStoredNotifications([]);
      setNotificationCount(0);
    }
  };

  const fetchOfflineNotifications = async () => {
    try {
      const response = await notificationAPI.getNotifications();
      const dbNotifications = response.data.notifications || [];
      
      // Get already fetched notification IDs from localStorage
      const fetchedIds = JSON.parse(localStorage.getItem('fetched_notification_ids') || '[]');
      
      // Only get notifications from last 2 hours that haven't been fetched
      const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000);
      const newNotifications = dbNotifications.filter((n: any) => 
        new Date(n.created_at + 'Z') > twoHoursAgo && 
        !n.is_read && 
        !fetchedIds.includes(n.id)
      );
      
      if (newNotifications.length > 0) {
        const convertedNotifications = newNotifications.map((n: any) => ({
          id: `db_${n.id}`,
          title: n.title,
          message: n.message,
          type: n.status === 'deployed' ? 'success' : n.status === 'failed' ? 'error' : 'info',
          timestamp: new Date(n.created_at + 'Z'),
          read: false,
          deployment_details: n.deployment_details
        }));
        
        // Show popup only for truly new notifications
        const uniqueNew = convertedNotifications.filter(newNotif => 
          !storedNotifications.some(existingNotif => 
            existingNotif.title === newNotif.title && 
            existingNotif.message === newNotif.message &&
            Math.abs(new Date(existingNotif.timestamp).getTime() - new Date(newNotif.timestamp).getTime()) < 30000
          )
        );
        
        if (uniqueNew.length > 0) {
          const newestNotification = uniqueNew[0];
          setSnackbarMessage(newestNotification.message);
          setSnackbarSeverity(newestNotification.type);
          setSnackbarOpen(true);
          console.log('✅ HTTP POPUP:', newestNotification.title);
          
          if (soundEnabled) {
            playNotificationSound();
          }
        }
        
        // Add new notifications to existing ones with duplicate check
        setStoredNotifications(prev => {
          // Filter out duplicates from convertedNotifications
          const uniqueNew = convertedNotifications.filter(newNotif => 
            !prev.some(existingNotif => 
              existingNotif.title === newNotif.title && 
              existingNotif.message === newNotif.message &&
              Math.abs(new Date(existingNotif.timestamp).getTime() - new Date(newNotif.timestamp).getTime()) < 30000
            )
          );
          
          if (uniqueNew.length === 0) {
            console.log('🚫 All HTTP notifications were duplicates, skipping');
            return prev;
          }
          
          const updated = [...uniqueNew, ...prev].slice(0, 20);
          updateNotificationCount(updated);
          localStorage.setItem('layout_notifications', JSON.stringify(updated));
          console.log(`✅ Added ${uniqueNew.length} unique HTTP notifications`);
          return updated;
        });
        
        // Mark these notifications as fetched
        const newFetchedIds = [...fetchedIds, ...newNotifications.map(n => n.id)];
        localStorage.setItem('fetched_notification_ids', JSON.stringify(newFetchedIds));
      }
    } catch (error) {
      // Silently handle offline notification errors
    }
  };

  const playNotificationSound = () => {
    if (soundEnabled) {
      try {
        const audio = new Audio('/notification.mp3');
        audio.volume = 0.3;
        audio.play().catch(() => {
          // Fallback to system beep if audio file not available
          try {
            if ('vibrate' in navigator) {
              navigator.vibrate(200);
            }
          } catch (vibrateError) {
            // Vibration not supported, ignore
          }
        });
      } catch (error) {
        // Audio not available, ignore
      }
    }
  };



  const updateNotificationCount = (notifications: StoredNotification[]) => {
    const unreadCount = notifications.filter(n => !n.read).length;
    setNotificationCount(unreadCount);
  };

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const handleNavigation = (path: string) => {
    navigate(path);
    if (isMobile) {
      setMobileOpen(false);
    }
  };

  const handleBackToLogin = () => {
    logout();
    navigate('/login');
  };

  const handleNotificationClick = (event: React.MouseEvent<HTMLElement>) => {
    setNotificationAnchor(event.currentTarget);
  };

  const handleNotificationClose = () => {
    setNotificationAnchor(null);
  };

  const markNotificationAsRead = async (id: string) => {
    const updatedNotifications = storedNotifications.map(n => 
      n.id === id ? { ...n, read: true } : n
    );
    setStoredNotifications(updatedNotifications);
    updateNotificationCount(updatedNotifications);
    localStorage.setItem('layout_notifications', JSON.stringify(updatedNotifications));
    
    // Mark as read in backend if it's a database notification
    if (id.startsWith('db_')) {
      try {
        const dbId = id.replace('db_', '');
        await notificationAPI.markAsRead(dbId);
      } catch (error) {
        console.error('Failed to mark notification as read in backend');
      }
    }
  };

  const markAllNotificationsAsRead = async () => {
    const updatedNotifications = storedNotifications.map(n => ({ ...n, read: true }));
    localStorage.setItem('layout_notifications', JSON.stringify(updatedNotifications));
    setStoredNotifications(updatedNotifications);
    setNotificationCount(0);
    
    // Mark all as read in backend
    try {
      await notificationAPI.markAllAsRead();
    } catch (error) {
      console.error('Failed to mark all notifications as read in backend');
    }
    
    handleNotificationClose();
  };

  const clearAllNotifications = async () => {
    try {
      // Clear from backend database
      await notificationAPI.clearAll();
    } catch (error) {
      console.error('Failed to clear notifications from backend');
    }
    
    // Clear from frontend
    localStorage.removeItem('layout_notifications');
    localStorage.removeItem('fetched_notification_ids'); // Clear fetched IDs
    setStoredNotifications([]);
    setNotificationCount(0);
    handleNotificationClose();
  };

  const toggleNotificationExpansion = (id: string) => {
    const newExpanded = new Set(expandedNotifications);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedNotifications(newExpanded);
  };

  const toggleSound = () => {
    setSoundEnabled(!soundEnabled);
    localStorage.setItem('notification_sound_enabled', (!soundEnabled).toString());
  };

  const toggleRealTimeUpdates = () => {
    setRealTimeUpdates(!realTimeUpdates);
    localStorage.setItem('real_time_updates_enabled', (!realTimeUpdates).toString());
  };

  useEffect(() => {
    const soundPref = localStorage.getItem('notification_sound_enabled');
    if (soundPref !== null) {
      setSoundEnabled(soundPref === 'true');
    }
    
    const updatesPref = localStorage.getItem('real_time_updates_enabled');
    if (updatesPref !== null) {
      setRealTimeUpdates(updatesPref === 'true');
    }
  }, []);

  const getEnvironmentChips = () => {
    const allEnvironments = ['dev', 'qa', 'prod'];
    const now = new Date();
    
    // Get default environment based on user department
    const getDefaultEnvironment = () => {
      const dept = user?.department?.toLowerCase();
      if (dept?.includes('prod') || dept?.includes('production')) return 'prod';
      if (dept?.includes('qa') || dept?.includes('test') || dept?.includes('quality')) return 'qa';
      return 'dev'; // Default fallback
    };
    
    const defaultEnv = getDefaultEnvironment();
    
    return allEnvironments.map((env) => {
      const hasDefaultAccess = env === defaultEnv;
      const hasApprovedAccess = user?.environment_access?.[env] || false;
      const expiry = user?.environment_expiry?.[env];
      
      // Fix expiry check - handle UTC dates properly
      let isExpired = false;
      if (expiry && hasApprovedAccess) {
        try {
          const expiryDate = new Date(expiry.endsWith('Z') ? expiry : expiry + 'Z');
          isExpired = now > expiryDate;
        } catch (e) {
          isExpired = true; // Treat invalid dates as expired
        }
      }
      
      // Only show active if: default access OR (approved access AND not expired)
      const isActive = hasDefaultAccess || (hasApprovedAccess && !isExpired);
      
      return (
        <Chip
          key={env}
          label={env.toUpperCase()}
          size="small"
          color={
            isActive 
              ? (env === 'prod' ? 'error' : env === 'qa' ? 'warning' : 'success')
              : 'default'
          }
          variant={isActive ? 'filled' : 'outlined'}
          sx={{ 
            mr: 0.5, 
            mb: 0.5,
            opacity: isActive ? 1 : 0.4,
            fontWeight: isActive ? 600 : 400,
            '&.MuiChip-filled': {
              fontWeight: 600
            },
            '&.MuiChip-outlined': {
              borderStyle: 'dashed',
              color: 'text.disabled'
            }
          }}
          title={
            hasDefaultAccess ? `Default ${env} environment (based on ${user?.department} department)` :
            isExpired ? `Access expired on ${expiry ? new Date(expiry.endsWith('Z') ? expiry : expiry + 'Z').toLocaleDateString() : 'unknown date'}` :
            hasApprovedAccess ? `Approved access (expires ${expiry ? new Date(expiry.endsWith('Z') ? expiry : expiry + 'Z').toLocaleDateString() : 'unknown date'})` :
            `No access to ${env} environment`
          }
        />
      );
    });
  };

  const formatTimeAgo = (timestamp: Date | string) => {
    const now = new Date();
    // Handle UTC timestamps correctly
    let date: Date;
    if (timestamp instanceof Date) {
      date = timestamp;
    } else {
      // Ensure UTC parsing
      date = new Date(timestamp.endsWith('Z') ? timestamp : timestamp + 'Z');
    }
    
    // Check if date is valid
    if (isNaN(date.getTime())) {
      return 'Just now';
    }
    
    // Use current time for calculation
    const diffMs = now.getTime() - date.getTime();
    const diffSeconds = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffSeconds / 60);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffSeconds < 60) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  const renderNotificationDetails = (notification: StoredNotification) => {
    if (!notification.deployment_details || notification.type !== 'success') return null;

    const details = notification.deployment_details;
    
    return (
      <Box sx={{ mt: 1, p: 2, bgcolor: '#f8f9fa', borderRadius: 1 }}>
        {details.instance_id && (
          <Typography variant="body2" sx={{ mb: 1 }}>
            <strong>Instance ID:</strong> {details.instance_id}
          </Typography>
        )}
        {details.ip_address && (
          <Typography variant="body2" sx={{ mb: 1 }}>
            <strong>{details.ip_type?.toUpperCase() || 'IP'} Address:</strong> {details.ip_address}
          </Typography>
        )}
        {details.console_url && (
          <Button
            size="small"
            variant="outlined"
            startIcon={<Launch />}
            onClick={(e) => {
              e.stopPropagation();
              const url = details.console_url;
              if (url && (url.startsWith('https://console.aws.amazon.com/') || url.startsWith('https://aws.amazon.com/'))) {
                window.open(url, '_blank', 'noopener,noreferrer');
              }
            }}
            sx={{ mt: 1 }}
          >
            Open Console
          </Button>
        )}
      </Box>
    );
  };

  const drawer = (
    <Box>
      <Box sx={{ 
        p: 3, 
        backgroundColor: '#f8f9fa',
        borderBottom: '1px solid #e0e0e0'
      }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <CloudQueue sx={{ fontSize: 32, color: '#1976d2' }} />
          <Typography variant="h6" fontWeight="bold" color="#424242">
            AiOps Platform
          </Typography>
        </Box>
        
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <Avatar sx={{ bgcolor: '#1976d2', width: 40, height: 40 }}>
            {user?.name?.charAt(0).toUpperCase()}
          </Avatar>
          <Box>
            <Typography variant="subtitle2" fontWeight="medium" color="#424242">
              Hello, {user?.name || 'User'}! 👋
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {user?.department || 'Unknown'} Department
            </Typography>
          </Box>
        </Box>
        
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
            Environment Access:
          </Typography>
          {getEnvironmentChips()}
        </Box>
      </Box>

      <Divider />

      <List sx={{ pt: 1 }}>
        {menuItems.map((item) => (
          <ListItem key={item.text} disablePadding>
            <ListItemButton
              selected={location.pathname === item.path}
              onClick={() => handleNavigation(item.path)}
              sx={{
                mx: 1,
                mb: 0.5,
                borderRadius: 2,
                '&.Mui-selected': {
                  backgroundColor: '#e3f2fd',
                  color: '#1976d2',
                  '&:hover': {
                    backgroundColor: '#bbdefb',
                  }
                }
              }}
            >
              <ListItemIcon sx={{ 
                color: location.pathname === item.path ? '#1976d2' : 'inherit',
                minWidth: 40
              }}>
                {item.icon}
              </ListItemIcon>
              <ListItemText primary={item.text} />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', height: '100vh' }}>
      <AppBar
        position="fixed"
        sx={{
          width: { md: `calc(100% - ${drawerWidth}px)` },
          ml: { md: `${drawerWidth}px` },
          backgroundColor: 'white',
          color: '#424242',
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
        }}
      >
        <Toolbar>
          <IconButton
            color="inherit"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { md: 'none' } }}
          >
            <MenuIcon />
          </IconButton>

          <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
            {menuItems.find(item => item.path === location.pathname)?.text || 'AiOps Platform'}
          </Typography>

          <IconButton
            size="large"
            edge="end"
            onClick={handleBackToLogin}
            color="inherit"
            title="Back to Login"
            sx={{ mr: 1 }}
          >
            <ArrowBack />
          </IconButton>

          <IconButton
            size="large"
            edge="end"
            onClick={handleNotificationClick}
            color="inherit"
          >
            <Badge badgeContent={notificationCount} color="error">
              {notificationCount > 0 ? <NotificationsActive /> : <Notifications />}
            </Badge>
          </IconButton>
        </Toolbar>
      </AppBar>

      <Menu
        anchorEl={notificationAnchor}
        open={Boolean(notificationAnchor)}
        onClose={handleNotificationClose}
        PaperProps={{
          sx: { width: 450, maxHeight: 600 }
        }}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'right',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'right',
        }}
      >
        <Box sx={{ p: 2, borderBottom: 1, borderColor: 'divider' }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
            <Typography variant="h6">Notifications</Typography>
            <IconButton size="small" onClick={toggleSound} title={soundEnabled ? 'Disable sound' : 'Enable sound'}>
              <VolumeUp color={soundEnabled ? 'primary' : 'disabled'} />
            </IconButton>
          </Box>
          
          {storedNotifications.length > 0 && (
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button size="small" onClick={markAllNotificationsAsRead}>
                Mark all read
              </Button>
              <Button size="small" onClick={clearAllNotifications} startIcon={<Clear />}>
                Clear all
              </Button>
            </Box>
          )}
        </Box>

        <Box sx={{ maxHeight: 450, overflow: 'auto' }}>
          {storedNotifications.length === 0 ? (
            <MenuItem disabled>
              <Typography variant="body2" color="text.secondary">
                No notifications
              </Typography>
            </MenuItem>
            ) : (
            storedNotifications.slice(0, 20).map((notification) => (
              <Box key={notification.id} sx={{ borderBottom: '1px solid #e0e0e0' }}>
                <Accordion
                  expanded={expandedNotifications.has(notification.id)}
                  onChange={() => toggleNotificationExpansion(notification.id)}
                  elevation={0}
                  disableGutters
                  sx={{
                    opacity: notification.read ? 0.6 : 1,
                    '&:before': { display: 'none' },
                    borderLeft: notification.read ? 'none' : `3px solid ${
                      notification.type === 'success' ? '#4caf50' : 
                      notification.type === 'error' ? '#f44336' : 
                      notification.type === 'warning' ? '#ff9800' : '#2196f3'
                    }`
                  }}
                >
                  <AccordionSummary
                    expandIcon={<ExpandMore />}
                    onClick={() => markNotificationAsRead(notification.id)}
                    sx={{ 
                      minHeight: 'auto',
                      '& .MuiAccordionSummary-content': { margin: '12px 0' }
                    }}
                  >
                    <Box sx={{ width: '100%' }}>
                      <Typography variant="subtitle2" sx={{ fontWeight: notification.read ? 400 : 600 }}>
                        {notification.title}
                      </Typography>
                      <Typography 
                        variant="body2" 
                        color="text.secondary" 
                        sx={{ 
                          mb: 0.5,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical'
                        }}
                      >
                        {notification.message}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatTimeAgo(notification.timestamp)}
                      </Typography>
                    </Box>
                  </AccordionSummary>
                  <AccordionDetails sx={{ pt: 0 }}>
                    <Typography variant="body2" sx={{ mb: 1 }}>
                      {notification.message}
                    </Typography>
                    {renderNotificationDetails(notification)}
                  </AccordionDetails>
                </Accordion>
              </Box>
            ))
          )}
        </Box>
      </Menu>

      <Box
        component="nav"
        sx={{ width: { md: drawerWidth }, flexShrink: { md: 0 } }}
      >
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', md: 'none' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
          }}
        >
          {drawer}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', md: 'block' },
            '& .MuiDrawer-paper': { boxSizing: 'border-box', width: drawerWidth },
          }}
          open
        >
          {drawer}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          width: { md: `calc(100% - ${drawerWidth}px)` },
          mt: '64px',
          height: 'calc(100vh - 64px)',
          overflow: 'hidden'
        }}
      >
        {children}
      </Box>
      
      {/* Snackbar for popup notifications */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={18000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setSnackbarOpen(false)}
          severity={snackbarSeverity}
          variant="filled"
          sx={{ width: '100%' }}
        >
          {snackbarMessage}
        </Alert>
      </Snackbar>
    </Box>
  );
}