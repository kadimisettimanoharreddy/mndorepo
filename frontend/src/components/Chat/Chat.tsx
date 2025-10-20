import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Paper,
  TextField,
  IconButton,
  Typography,
  List,
  ListItem,
  Button,
  Alert,
  CircularProgress,
  InputAdornment,
  Snackbar
} from '@mui/material';
import {
  Send,
  ArrowBack,
  SmartToy,
  Person,
  Build,
  Close,
  Refresh
} from '@mui/icons-material';
import { useAuth } from '../../contexts/AuthContext';
import { useWebSocket } from '../../contexts/WebSocketContext';
import { useNavigate } from 'react-router-dom';

interface Message {
  id: string;
  type: 'user' | 'bot' | 'system';
  content: string;
  timestamp: Date;
  buttons?: ButtonOption[];
}

interface ButtonOption {
  text: string;
  value: string;
  variant?: 'contained' | 'outlined';
  color?: 'primary' | 'secondary' | 'success' | 'error';
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [processing, setProcessing] = useState(false);
  const { ws, connected, sendMessage: wsSendMessage } = useWebSocket();
  const [showTextInput, setShowTextInput] = useState(true);
  const [greetingShown, setGreetingShown] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const conversationKeyRef = useRef<string>('');
  
  const { user, refreshUser } = useAuth();
  const navigate = useNavigate();
  const wsRef = useRef<WebSocket | null>(null);
  const conversationLoadedRef = useRef<string | null>(null);

  useEffect(() => {
    console.log('Chat: User data changed:', user);
    if (user?.id) {
      // Check if this is a fresh login or just navigation
      const currentLoginTime = localStorage.getItem('login_time');
      const lastChatSession = sessionStorage.getItem(`chat_session_${user.id}`);
      
      if (lastChatSession === currentLoginTime) {
        // Same session - restore conversation
        const savedMessages = sessionStorage.getItem(`chat_messages_${user.id}`);
        const existingKey = sessionStorage.getItem(`chat_key_${user.id}`);
        
        if (existingKey && savedMessages) {
          try {
            const parsed = JSON.parse(savedMessages);
            if (Array.isArray(parsed) && parsed.length > 0) {
              conversationKeyRef.current = existingKey;
              setMessages(parsed.map(m => ({...m, timestamp: new Date(m.timestamp)})));
              setGreetingShown(true);
              console.log('Chat: Restored conversation with', parsed.length, 'messages');
              return;
            }
          } catch (e) {
            console.error('Failed to load saved messages:', e);
          }
        }
      }
      
      // Fresh login - start new conversation
      initializeNewConversation();
      // Mark this as current session
      if (currentLoginTime) {
        sessionStorage.setItem(`chat_session_${user.id}`, currentLoginTime);
      }
      // Add welcome message
      setTimeout(() => {
        addWelcomeMessage();
      }, 500);
    }
  }, [user?.id]);

  const initializeNewConversation = () => {
    conversationKeyRef.current = `chat_${user?.id}_${Date.now()}`;
    setMessages([]);
    setGreetingShown(false);
    // Clear any existing session chat data for fresh start
    if (user?.id) {
      sessionStorage.removeItem(`chat_messages_${user.id}`);
      sessionStorage.removeItem(`chat_key_${user.id}`);
    }
  };



  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const addWelcomeMessage = () => {
    // Check if greeting was already shown in this browser session
    const greetingKey = `greeting_shown_${user?.id}`;
    const greetingShownInSession = sessionStorage.getItem(greetingKey);
    
    console.log('Chat: Checking greeting - shown in session:', greetingShownInSession);
    
    // Only add welcome message if not shown in this browser session
    if (!greetingShownInSession) {
      const welcomeMessage: Message = {
        id: 'welcome',
        type: 'bot', 
        content: `Hi ${user?.name || 'there'}! 👋 Welcome to the Infrastructure Assistant! I'm here to help you create and manage AWS resources. What would you like to deploy today?`,
        timestamp: new Date()
      };
      setMessages([welcomeMessage]);
      setGreetingShown(true);
      // Mark greeting as shown for this browser session only
      sessionStorage.setItem(greetingKey, 'true');
      console.log('Chat: Welcome message added');
    }
  };

  const processedMessages = useRef(new Set<string>());
  const messageHandlerRef = useRef<((event: MessageEvent) => void) | null>(null);
  
  const setupWebSocketListeners = () => {
    if (!ws) return;
    
    // Remove existing listener if any
    if (messageHandlerRef.current) {
      ws.removeEventListener('message', messageHandlerRef.current);
    }
    
    wsRef.current = ws;
    
    const handleMessage = (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      
      // Prevent duplicate message processing with better ID generation
      const messageId = data.message_id || `${data.type}_${data.timestamp || Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      if (processedMessages.current.has(messageId)) {
        console.log('🚫 Duplicate message blocked:', messageId);
        return;
      }
      processedMessages.current.add(messageId);
      
      // Clean up old message IDs (keep last 50)
      if (processedMessages.current.size > 50) {
        const ids = Array.from(processedMessages.current);
        processedMessages.current = new Set(ids.slice(-25));
      }
      
      if (data.type === 'connection_ready') {
        console.log('Connection ready received');
        setGreetingShown(true);
      } else if (data.type === 'chat_response') {
        console.log('📨 Processing chat response:', messageId);
        addBotMessage(data.message, data.buttons);
        setProcessing(false);
        setShowTextInput(data.show_text_input !== false);
        
        if (data.greeting) {
          setGreetingShown(true);
        }
      } else if (data.type === 'popup_notification') {
        console.log('🔔 Chat: Ignoring popup notification - handled by Layout');
      } else if (data.type === 'approval_notification') {
        const isApproved = data.approved;
        addToLayoutNotifications({
          title: isApproved ? "Environment Access Approved!" : "Environment Access Denied",
          message: data.message,
          type: isApproved ? "success" : "error"
        });
        
        addBotMessage(`${isApproved ? '✅' : '❌'} ${data.message}`);
        
        if (isApproved && refreshUser) {
          setTimeout(() => {
            refreshUser();
          }, 1000);
        }
      }
    };
    
    messageHandlerRef.current = handleMessage;
    ws.addEventListener('message', handleMessage);
    
    return () => {
      if (messageHandlerRef.current) {
        ws.removeEventListener('message', messageHandlerRef.current);
        messageHandlerRef.current = null;
      }
    };
  };
  
  useEffect(() => {
    if (ws && user?.id) {
      try {
        const cleanup = setupWebSocketListeners();
        // Preserve connection during navigation but clean up properly
        return cleanup;
      } catch (error) {
        console.error('Failed to setup WebSocket listeners');
        return () => {};
      }
    }
  }, [ws, user?.id]);
  
  // Remove backup listener to prevent duplicate processing
  // WebSocket direct listener is sufficient

  const addToLayoutNotifications = (popup: any) => {
    try {
      const stored = localStorage.getItem('layout_notifications') || '[]';
      const notifications = JSON.parse(stored);
      
      const newNotification = {
        id: popup.id || Date.now().toString(),
        title: popup.title,
        message: popup.message,
        type: popup.type || 'info',
        timestamp: new Date(),
        read: false
      };
      
      // Check for duplicates before adding
      const isDuplicate = notifications.some((n: any) => 
        n.title === newNotification.title && 
        n.message === newNotification.message &&
        Math.abs(new Date(n.timestamp).getTime() - newNotification.timestamp.getTime()) < 5000
      );
      
      if (!isDuplicate) {
        notifications.unshift(newNotification);
        localStorage.setItem('layout_notifications', JSON.stringify(notifications.slice(0, 50)));
      }
    } catch (error) {
      console.error('Error saving to layout notifications');
    }
  };

  const addMessage = (type: 'user' | 'bot' | 'system', content: string, buttons?: ButtonOption[]) => {
    const newMessage: Message = {
      id: `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      type,
      content,
      timestamp: new Date(),
      buttons
    };
    setMessages(prev => {
      const updated = [...prev, newMessage];
      // Save to sessionStorage for navigation persistence within same login
      if (user?.id) {
        try {
          sessionStorage.setItem(`chat_messages_${user.id}`, JSON.stringify(updated));
          sessionStorage.setItem(`chat_key_${user.id}`, conversationKeyRef.current);
        } catch (e) {
          console.error('Failed to save messages:', e);
        }
      }
      return updated;
    });
  };

  const addBotMessage = (content: string, buttons?: ButtonOption[]) => {
    addMessage('bot', content, buttons);
  };

  const sendMessage = (message?: string) => {
    const messageToSend = message || inputValue.trim();
    if (!messageToSend || !connected) return;

    addMessage('user', messageToSend);
    setProcessing(true);

    wsSendMessage({
      type: 'chat_message',
      message: messageToSend,
      conversation_key: conversationKeyRef.current,
      timestamp: new Date().toISOString()
    });

    setInputValue('');
    
    // Save conversation state for navigation persistence
    if (user?.id) {
      sessionStorage.setItem(`chat_key_${user.id}`, conversationKeyRef.current);
    }
  };

  const handleButtonClick = (value: string, text: string) => {
    sendMessage(value);
  };

  const clearChat = () => {
    if (processing) return;
    
    // Clear current conversation
    processedMessages.current.clear();
    conversationKeyRef.current = `chat_${user?.id}_${Date.now()}`;
    setMessages([]);
    setGreetingShown(false);
    setShowTextInput(true);
    
    // Clear session data to allow new greeting
    if (user?.id) {
      sessionStorage.removeItem(`greeting_shown_${user?.id}`);
      sessionStorage.removeItem(`chat_messages_${user.id}`);
      sessionStorage.removeItem(`chat_key_${user.id}`);
    }
    
    // Send clear conversation to backend
    if (connected) {
      wsSendMessage({
        type: 'clear_conversation',
        conversation_key: conversationKeyRef.current,
        timestamp: new Date().toISOString()
      });
    }
    
    // Add better greeting message after clearing
    setTimeout(() => {
      const welcomeMessage: Message = {
        id: `welcome_${Date.now()}`,
        type: 'bot', 
        content: `Chat cleared! I'm ready to help you create new infrastructure. What would you like to build?`,
        timestamp: new Date()
      };
      setMessages([welcomeMessage]);
    }, 500);
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (!user) {
    return null;
  }

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      <Box sx={{ 
        p: 3, 
        borderBottom: 1, 
        borderColor: 'divider',
        background: 'linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)',
        color: 'text.primary'
      }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Build sx={{ color: 'primary.main' }} />
            <Box>
              <Typography variant="h6" sx={{ color: 'text.primary', fontWeight: 600 }}>
                Infrastructure Assistant
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Box sx={{ 
                  width: 8, 
                  height: 8, 
                  bgcolor: connected ? '#4caf50' : '#f44336', 
                  borderRadius: '50%'
                }} />
                <Typography variant="caption" color="text.secondary">
                  {connected ? 'Connected' : 'Connecting...'}
                </Typography>
              </Box>
            </Box>
          </Box>
          
          <Box sx={{ display: 'flex', gap: 1 }}>
            <IconButton 
              onClick={clearChat} 
              disabled={processing}
              title="Refresh - Clear conversation"
              sx={{ 
                color: 'text.secondary',
                '&:hover': { bgcolor: 'action.hover' }
              }}
            >
              <Refresh />
            </IconButton>
          </Box>
        </Box>
      </Box>

      <Box sx={{ 
        flexGrow: 1, 
        overflow: 'auto', 
        p: 2,
        backgroundColor: '#fafafa'
      }}>
        <List sx={{ py: 0 }}>
          {messages.map((message) => (
            <ListItem key={message.id} sx={{ py: 2, px: 1, alignItems: 'flex-start' }}>
              <Box sx={{ 
                display: 'flex', 
                width: '100%',
                justifyContent: message.type === 'user' ? 'flex-end' : 'flex-start'
              }}>
                <Box sx={{ maxWidth: '75%' }}>
                  <Paper 
                    elevation={2}
                    sx={{
                      p: 3,
                      backgroundColor: message.type === 'user' 
                        ? '#667eea'
                        : message.type === 'system'
                        ? '#fff3cd'
                        : 'white',
                      color: message.type === 'user' ? 'white' : 'text.primary',
                      borderRadius: message.type === 'user' 
                        ? '20px 20px 6px 20px'
                        : '20px 20px 20px 6px',
                      boxShadow: message.type === 'user' 
                        ? '0 4px 12px rgba(102, 126, 234, 0.3)'
                        : '0 2px 8px rgba(0, 0, 0, 0.08)'
                    }}
                  >
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                      {message.type === 'user' ? (
                        <Person fontSize="small" sx={{ opacity: 0.9 }} />
                      ) : message.type === 'bot' ? (
                        <SmartToy fontSize="small" sx={{ color: 'primary.main' }} />
                      ) : null}
                      <Typography variant="caption" sx={{ 
                        opacity: message.type === 'user' ? 0.9 : 0.7,
                        fontWeight: 500
                      }}>
                        {message.type === 'user' ? user?.name : 
                         message.type === 'bot' ? 'Assistant' : 'System'}
                      </Typography>
                    </Box>
                    
                    <Typography 
                      variant="body1" 
                      sx={{ 
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        lineHeight: 1.5
                      }}
                    >
                      {message.content}
                    </Typography>
                  </Paper>

                  {message.buttons && message.buttons.length > 0 && (
                    <Box sx={{ mt: 2, display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                      {message.buttons.map((button, index) => (
                        <Button
                          key={index}
                          variant={button.variant || 'outlined'}
                          color={button.color || 'primary'}
                          onClick={() => handleButtonClick(button.value, button.text)}
                          disabled={processing}
                          sx={{
                            borderRadius: 20,
                            textTransform: 'none',
                            px: 3,
                            py: 1,
                            fontSize: '0.875rem',
                            fontWeight: 500
                          }}
                        >
                          {button.text}
                        </Button>
                      ))}
                    </Box>
                  )}
                </Box>
              </Box>
            </ListItem>
          ))}
          
          {processing && (
            <ListItem sx={{ py: 2, px: 1 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <SmartToy sx={{ color: 'primary.main' }} />
                <CircularProgress size={20} sx={{ color: 'primary.main' }} />
                <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                  Assistant is thinking...
                </Typography>
              </Box>
            </ListItem>
          )}
        </List>
        <div ref={messagesEndRef} />
      </Box>

      {showTextInput && (
        <Paper 
          elevation={4} 
          sx={{ 
            p: 3, 
            m: 2, 
            borderRadius: 20,
            background: 'white',
            border: '1px solid',
            borderColor: 'divider'
          }}
        >
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-end' }}>
            <TextField
              fullWidth
              multiline
              maxRows={4}
              placeholder="Ask me anything about infrastructure..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={!connected || processing}
              variant="outlined"
              sx={{
                '& .MuiOutlinedInput-root': {
                  borderRadius: 15,
                  backgroundColor: '#f8f9fa',
                  border: 'none',
                  '&:hover': {
                    backgroundColor: '#f1f3f4',
                  },
                  '&.Mui-focused': {
                    backgroundColor: 'white',
                    boxShadow: '0 0 0 2px rgba(102, 126, 234, 0.2)'
                  }
                },
                '& .MuiOutlinedInput-notchedOutline': {
                  border: 'none'
                }
              }}
              InputProps={{
                endAdornment: inputValue.trim() && (
                  <InputAdornment position="end">
                    <Typography variant="caption" color="text.secondary">
                      Press Enter to send
                    </Typography>
                  </InputAdornment>
                )
              }}
            />
            <IconButton
              onClick={() => sendMessage()}
              disabled={!inputValue.trim() || !connected || processing}
              sx={{
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                color: 'white',
                width: 48,
                height: 48,
                '&:hover': {
                  background: 'linear-gradient(135deg, #5a67d8 0%, #68577a 100%)',
                  transform: 'scale(1.05)'
                },
                '&:disabled': {
                  background: '#e0e0e0',
                  color: '#9e9e9e',
                  transform: 'none'
                },
                transition: 'all 0.2s ease'
              }}
            >
              <Send />
            </IconButton>
          </Box>
          
          {!connected && (
            <Alert severity="warning" sx={{ mt: 2, borderRadius: 2 }}>
              Not connected to chat service. Please refresh the page.
            </Alert>
          )}
        </Paper>
      )}

    </Box>
  );
}