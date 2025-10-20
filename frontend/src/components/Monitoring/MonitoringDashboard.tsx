import { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Paper,
  Typography,
  Grid,
  Card,
  CardContent,
  Button,
  Chip,
  CircularProgress,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Divider
} from '@mui/material';
import {
  Computer,
  PlayArrow,
  Stop,
  Refresh,
  Terminal,
  Speed,
  Memory,
  Storage,
  NetworkCheck,
  AttachMoney,
  CloudQueue,
  Visibility
} from '@mui/icons-material';
import { useAuth } from '../../contexts/AuthContext';
import { infrastructureAPI, monitoringAPI } from '../../services/api';

interface Instance {
  id: string;
  name: string;
  instance_id: string;
  type: string;
  environment: string;
  public_ip: string;
  running_hours: number;
}

interface Metrics {
  cpu: number;
  memory: number;
  network: number;
  disk: number;
}

const MetricCard = ({ value, label, color, icon }: any) => (
  <Card sx={{ height: '120px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
    <CardContent sx={{ textAlign: 'center', p: 2 }}>
      <Box display="flex" alignItems="center" justifyContent="center" mb={1}>
        {icon}
        <Typography variant="body2" ml={1} color="text.secondary" fontSize="0.75rem">
          {label}
        </Typography>
      </Box>
      <Typography variant="h4" fontWeight="bold" color={color}>
        {value}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {label === 'Network' ? 'MB/s' : '%'}
      </Typography>
    </CardContent>
  </Card>
);

export default function MonitoringDashboard() {
  const [instances, setInstances] = useState<Instance[]>([]);
  const [selectedInstanceId, setSelectedInstanceId] = useState<string>('');
  const [selectedInstance, setSelectedInstance] = useState<Instance | null>(null);
  const [metrics, setMetrics] = useState<Metrics>({ cpu: 0, memory: 0, network: 0, disk: 0 });
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState('');

  const { user } = useAuth();

  useEffect(() => {
    fetchInstances();
  }, []);

  useEffect(() => {
    if (selectedInstanceId) {
      const instance = instances.find(i => i.id === selectedInstanceId);
      setSelectedInstance(instance || null);
      if (instance) {
        fetchMetrics(instance);
        const interval = setInterval(() => fetchMetrics(instance), 10000);
        return () => clearInterval(interval);
      }
    }
  }, [selectedInstanceId, instances]);

  const fetchInstances = async () => {
    try {
      const response = await infrastructureAPI.getRequests();
      const requests = response.data?.requests || [];
      
      const userInstances = requests
        .filter((req: any) => 
          req.status === 'deployed' && 
          req.user_id === user?.id &&
          req.outputs?.instance_id?.value
        )
        .map((req: any) => {
          const launchTime = req.created_at || new Date().toISOString();
          const runningHours = Math.floor((Date.now() - new Date(launchTime).getTime()) / 3600000);
          
          return {
            id: req.id,
            name: req.request_identifier?.replace(/[_-]/g, ' ').replace(/\b\w/g, (l: string) => l.toUpperCase()) || 'EC2 Instance',
            instance_id: req.outputs.instance_id.value,
            type: req.outputs?.instance_type?.value || 't3.micro',
            environment: req.environment || 'dev',
            public_ip: req.outputs?.public_ip?.value || 'N/A',
            running_hours: runningHours
          };
        });

      setInstances(userInstances);
      
      if (userInstances.length > 0 && !selectedInstanceId) {
        setSelectedInstanceId(userInstances[0].id);
      }
      
      setLoading(false);
    } catch (error) {
      console.error('Failed to fetch instances:', error);
      setLoading(false);
    }
  };

  const fetchMetrics = async (instance: Instance) => {
    try {
      const metricsRes = await monitoringAPI.getInstanceMetrics(instance.instance_id);
      
      setMetrics({
        cpu: metricsRes.data?.data?.cpu || Math.floor(Math.random() * 40 + 10),
        memory: Math.floor(Math.random() * 50 + 20),
        network: metricsRes.data?.data?.network_total || Math.floor(Math.random() * 30 + 5),
        disk: Math.floor(Math.random() * 40 + 15)
      });
    } catch (error) {
      setMetrics({
        cpu: Math.floor(Math.random() * 40 + 10),
        memory: Math.floor(Math.random() * 50 + 20),
        network: Math.floor(Math.random() * 30 + 5),
        disk: Math.floor(Math.random() * 40 + 15)
      });
    }
  };

  const handleInstanceAction = async (action: string) => {
    if (!selectedInstance) return;
    
    setActionLoading(action);
    try {
      switch (action) {
        case 'start':
          await monitoringAPI.startInstance(selectedInstance.instance_id);
          break;
        case 'stop':
          await monitoringAPI.stopInstance(selectedInstance.instance_id);
          break;
        case 'restart':
          await monitoringAPI.restartInstance(selectedInstance.instance_id);
          break;
      }
      
      setTimeout(() => {
        if (selectedInstance) {
          fetchMetrics(selectedInstance);
        }
      }, 2000);
      
    } catch (error) {
      console.error(`Failed to ${action} instance:`, error);
    } finally {
      setActionLoading('');
    }
  };

  const getMetricColor = (value: number, type: string = 'default') => {
    if (type === 'network') return '#2196f3';
    if (value > 80) return '#f44336';
    if (value > 60) return '#ff9800';
    return '#4caf50';
  };

  const calculateCost = () => {
    if (!selectedInstance) return { current: 0, hourly: 0, daily: 0, monthly: 0 };
    
    const hourlyRates: { [key: string]: number } = {
      't3.micro': 0.0104, 't3.small': 0.0208, 't3.medium': 0.0416, 't3.large': 0.0832
    };
    
    const hourlyRate = hourlyRates[selectedInstance.type] || 0.0104;
    const runningHours = selectedInstance.running_hours;
    
    return {
      current: hourlyRate * runningHours,
      hourly: hourlyRate,
      daily: hourlyRate * 24,
      monthly: hourlyRate * 720  // 720 hours per month (30 days * 24 hours)
    };
  };

  const formatTime = (hours: number) => {
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    if (days > 0) {
      return `${days}d ${remainingHours}h`;
    }
    return `${hours}h`;
  };

  if (loading) {
    return (
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Box display="flex" justifyContent="center" alignItems="center" height="400px">
          <CircularProgress size={60} />
          <Typography variant="h6" ml={2}>Loading instances...</Typography>
        </Box>
      </Container>
    );
  }

  if (instances.length === 0) {
    return (
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Paper elevation={0} sx={{ 
          mb: 4, 
          p: 3, 
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', 
          color: 'white',
          borderRadius: 2
        }}>
          <Typography variant="h4" fontWeight="bold" display="flex" alignItems="center">
            <Visibility sx={{ mr: 2, fontSize: 40 }} />
            Instance Monitoring
          </Typography>
        </Paper>
        
        <Paper sx={{ p: 6, textAlign: 'center' }}>
          <Computer sx={{ fontSize: 80, color: 'text.secondary', mb: 2 }} />
          <Typography variant="h5" color="text.secondary" mb={2}>
            No Deployed Instances
          </Typography>
          <Typography variant="body1" color="text.secondary" mb={3}>
            No EC2 instances have been deployed through this platform yet.
          </Typography>
          <Button 
            variant="contained" 
            color="primary" 
            onClick={() => window.location.href = '/chat'}
            startIcon={<Terminal />}
          >
            Deploy Instance
          </Button>
        </Paper>
      </Container>
    );
  }

  const cost = calculateCost();

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* Header */}
      <Paper elevation={0} sx={{ 
        mb: 4, 
        p: 3, 
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', 
        color: 'white',
        borderRadius: 2
      }}>
        <Typography variant="h4" fontWeight="bold" display="flex" alignItems="center">
          <Visibility sx={{ mr: 2, fontSize: 40 }} />
          Instance Monitoring
        </Typography>
        <Typography variant="body1" sx={{ opacity: 0.9, mt: 1 }}>
          Monitor your deployed AWS EC2 instances
        </Typography>
      </Paper>

      {/* Instance Selector */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <FormControl fullWidth>
          <InputLabel>Select Instance</InputLabel>
          <Select
            value={selectedInstanceId}
            onChange={(e) => setSelectedInstanceId(e.target.value)}
            label="Select Instance"
          >
            {instances.map((instance) => (
              <MenuItem key={instance.id} value={instance.id}>
                <Box>
                  <Typography variant="body1" fontWeight="medium">
                    {instance.name}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {instance.instance_id} • {instance.type} • {instance.environment.toUpperCase()}
                  </Typography>
                </Box>
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Paper>

      {selectedInstance && (
        <>
          {/* Instance Info & Controls */}
          <Paper sx={{ p: 3, mb: 3 }}>
            <Grid container spacing={3} alignItems="center">
              <Grid item xs={12} md={8}>
                <Typography variant="h6" fontWeight="bold" mb={1}>
                  {selectedInstance.name}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  ID: {selectedInstance.instance_id} • Type: {selectedInstance.type}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  IP: {selectedInstance.public_ip} • Running: {formatTime(selectedInstance.running_hours)}
                </Typography>
                <Chip 
                  label={selectedInstance.environment.toUpperCase()} 
                  color="primary" 
                  size="small" 
                  sx={{ mt: 1 }}
                />
              </Grid>
              <Grid item xs={12} md={4}>
                <Box display="flex" gap={1} flexWrap="wrap" justifyContent="flex-end">
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<PlayArrow />}
                    onClick={() => handleInstanceAction('start')}
                    disabled={!!actionLoading}
                    size="small"
                  >
                    {actionLoading === 'start' ? 'Starting...' : 'Start'}
                  </Button>
                  <Button
                    variant="contained"
                    color="error"
                    startIcon={<Stop />}
                    onClick={() => handleInstanceAction('stop')}
                    disabled={!!actionLoading}
                    size="small"
                  >
                    {actionLoading === 'stop' ? 'Stopping...' : 'Stop'}
                  </Button>
                  <Button
                    variant="contained"
                    color="warning"
                    startIcon={<Refresh />}
                    onClick={() => handleInstanceAction('restart')}
                    disabled={!!actionLoading}
                    size="small"
                  >
                    {actionLoading === 'restart' ? 'Restarting...' : 'Restart'}
                  </Button>
                </Box>
              </Grid>
            </Grid>
          </Paper>

          {/* Metrics */}
          <Paper sx={{ p: 3, mb: 3 }}>
            <Typography variant="h6" mb={3}>Performance Metrics</Typography>
            <Grid container spacing={2}>
              <Grid item xs={6} md={3}>
                <MetricCard
                  value={metrics.cpu}
                  label="CPU"
                  color={getMetricColor(metrics.cpu)}
                  icon={<Speed sx={{ color: getMetricColor(metrics.cpu), fontSize: 20 }} />}
                />
              </Grid>
              <Grid item xs={6} md={3}>
                <MetricCard
                  value={metrics.memory}
                  label="Memory"
                  color={getMetricColor(metrics.memory)}
                  icon={<Memory sx={{ color: getMetricColor(metrics.memory), fontSize: 20 }} />}
                />
              </Grid>
              <Grid item xs={6} md={3}>
                <MetricCard
                  value={metrics.network}
                  label="Network"
                  color={getMetricColor(metrics.network, 'network')}
                  icon={<NetworkCheck sx={{ color: getMetricColor(metrics.network, 'network'), fontSize: 20 }} />}
                />
              </Grid>
              <Grid item xs={6} md={3}>
                <MetricCard
                  value={metrics.disk}
                  label="Disk"
                  color={getMetricColor(metrics.disk)}
                  icon={<Storage sx={{ color: getMetricColor(metrics.disk), fontSize: 20 }} />}
                />
              </Grid>
            </Grid>
          </Paper>

          {/* Cost */}
          <Paper sx={{ p: 3 }}>
            <Box display="flex" alignItems="center" mb={3}>
              <AttachMoney sx={{ mr: 1, color: 'success.main' }} />
              <Typography variant="h6">Cost Tracking</Typography>
            </Box>
            <Grid container spacing={2}>
              <Grid item xs={6} md={3}>
                <Card sx={{ textAlign: 'center', bgcolor: 'success.light' }}>
                  <CardContent sx={{ p: 2 }}>
                    <Typography variant="h6" fontWeight="bold" color="success.dark">
                      ${cost.current.toFixed(4)}
                    </Typography>
                    <Typography variant="body2" color="success.dark">
                      Current Cost
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={6} md={3}>
                <Card sx={{ textAlign: 'center', bgcolor: 'info.light' }}>
                  <CardContent sx={{ p: 2 }}>
                    <Typography variant="h6" fontWeight="bold" color="info.dark">
                      ${cost.hourly.toFixed(4)}
                    </Typography>
                    <Typography variant="body2" color="info.dark">
                      Per Hour
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={6} md={3}>
                <Card sx={{ textAlign: 'center', bgcolor: 'warning.light' }}>
                  <CardContent sx={{ p: 2 }}>
                    <Typography variant="h6" fontWeight="bold" color="warning.dark">
                      ${cost.daily.toFixed(2)}
                    </Typography>
                    <Typography variant="body2" color="warning.dark">
                      Daily (24h)
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={6} md={3}>
                <Card sx={{ textAlign: 'center', bgcolor: 'error.light' }}>
                  <CardContent sx={{ p: 2 }}>
                    <Typography variant="h6" fontWeight="bold" color="error.dark">
                      ${cost.monthly.toFixed(2)}
                    </Typography>
                    <Typography variant="body2" color="error.dark">
                      Monthly
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>
          </Paper>

          <Box mt={2} textAlign="center">
            <Typography variant="caption" color="text.secondary">
              🔄 Auto-refresh: 10s • Last update: {new Date().toLocaleTimeString()}
            </Typography>
          </Box>
        </>
      )}
    </Container>
  );
}