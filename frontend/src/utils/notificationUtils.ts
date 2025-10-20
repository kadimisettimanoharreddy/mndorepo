// Notification deduplication utility
export interface NotificationData {
  id: string;
  title: string;
  message: string;
  type: 'success' | 'error' | 'info' | 'warning';
  timestamp: Date;
  read: boolean;
  deployment_details?: any;
}

const recentNotifications = new Map<string, number>();

export const isDuplicateNotification = (notification: NotificationData): boolean => {
  const key = `${notification.title}_${notification.message}`;
  const now = Date.now();
  const lastSeen = recentNotifications.get(key);
  
  // Consider it duplicate if same notification was seen within 5 seconds
  if (lastSeen && (now - lastSeen) < 5000) {
    return true;
  }
  
  recentNotifications.set(key, now);
  
  // Clean up old entries to prevent memory leak
  if (recentNotifications.size > 100) {
    const cutoff = now - 30000; // 30 seconds
    for (const [k, timestamp] of recentNotifications.entries()) {
      if (timestamp < cutoff) {
        recentNotifications.delete(k);
      }
    }
  }
  
  return false;
};

export const generateNotificationId = (title: string, message: string): string => {
  return `${Date.now()}_${title.slice(0, 10)}_${message.slice(0, 10)}`.replace(/\s/g, '_');
};