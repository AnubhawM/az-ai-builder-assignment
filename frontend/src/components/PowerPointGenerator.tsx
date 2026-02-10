import React, { useState, useRef, useCallback, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'react-toastify';
import Card from './ui/Card';

interface GenerationResult {
    message: string;
    output_directory: string;
    file_name?: string;
    status: 'pending' | 'completed' | 'error';
    start_timestamp?: number;
}

interface PPTFile {
    name: string;
    path: string;
    size_bytes: number;
    size_formatted: string;
    created_at: number;
}

interface StatusCheckResult {
    status: 'pending' | 'completed' | 'error';
    files: PPTFile[];
    all_files?: PPTFile[];
    message: string;
    output_directory: string;
}

// Helper function to format relative time
const getTimeAgo = (date: Date): string => {
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffSec < 60) return 'Just now';
    if (diffMin < 60) return `${diffMin} minute${diffMin > 1 ? 's' : ''} ago`;
    if (diffHour < 24) return `${diffHour} hour${diffHour > 1 ? 's' : ''} ago`;
    if (diffDay < 7) return `${diffDay} day${diffDay > 1 ? 's' : ''} ago`;
    return date.toLocaleDateString();
};


const PowerPointGenerator: React.FC = () => {
    const [topic, setTopic] = useState<string>('');
    const [loading, setLoading] = useState<boolean>(false);
    const [loadingStatus, setLoadingStatus] = useState<string>('');
    const [result, setResult] = useState<GenerationResult | null>(null);
    const [generatedFiles, setGeneratedFiles] = useState<PPTFile[]>([]);
    const [allFiles, setAllFiles] = useState<PPTFile[]>([]);
    const [pollCount, setPollCount] = useState<number>(0);
    const [loadingFiles, setLoadingFiles] = useState<boolean>(true);

    const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const statusTimeoutsRef = useRef<ReturnType<typeof setTimeout>[]>([]);

    const OUTPUT_DIRECTORY = '/Users/anubhawmathur/development/ppt-output';
    const MAX_POLL_ATTEMPTS = 60; // 5 minutes with 5-second intervals
    const POLL_INTERVAL_MS = 5000;

    // Fetch existing files from the output directory
    const fetchExistingFiles = useCallback(async () => {
        try {
            setLoadingFiles(true);
            const response = await axios.get<StatusCheckResult>(
                `${import.meta.env.VITE_API_URL}/check-ppt-status`,
                { params: { since: 0 } }
            );
            if (response.data.all_files) {
                setAllFiles(response.data.all_files);
            }
        } catch (error) {
            console.error('Error fetching existing files:', error);
        } finally {
            setLoadingFiles(false);
        }
    }, []);

    // Load existing files on mount
    useEffect(() => {
        fetchExistingFiles();
    }, [fetchExistingFiles]);

    const stopPolling = useCallback(() => {
        if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
        }
        // Clear any remaining status timeouts
        statusTimeoutsRef.current.forEach(t => clearTimeout(t));
        statusTimeoutsRef.current = [];
    }, []);

    const checkStatus = useCallback(async (startTimestamp: number, attemptCount: number) => {
        try {
            const response = await axios.get<StatusCheckResult>(
                `${import.meta.env.VITE_API_URL}/check-ppt-status`,
                { params: { since: startTimestamp } }
            );

            if (response.data.status === 'completed' && response.data.files.length > 0) {
                // Found new files!
                stopPolling();
                setLoading(false);
                setLoadingStatus('');
                setGeneratedFiles(response.data.files);
                // Also update the full file list
                if (response.data.all_files) {
                    setAllFiles(response.data.all_files);
                }
                setResult({
                    message: `Successfully generated ${response.data.files.length} PowerPoint file(s)!`,
                    output_directory: OUTPUT_DIRECTORY,
                    file_name: response.data.files[0].name,
                    status: 'completed'
                });
                toast.success(`🎉 PowerPoint generated: ${response.data.files[0].name}`);
                return true;
            }

            // Still pending
            if (attemptCount >= MAX_POLL_ATTEMPTS) {
                stopPolling();
                setLoading(false);
                setLoadingStatus('');
                setResult({
                    message: 'Generation is taking longer than expected. Please check the output directory manually.',
                    output_directory: OUTPUT_DIRECTORY,
                    status: 'pending'
                });
                toast.warning('Generation is still in progress. Check the output folder.');
                return true;
            }

            return false;
        } catch (error) {
            console.error('Error checking status:', error);
            return false;
        }
    }, [stopPolling]);

    const startPolling = useCallback((startTimestamp: number) => {
        let attempts = 0;

        pollingIntervalRef.current = setInterval(async () => {
            attempts++;
            setPollCount(attempts);

            const shouldStop = await checkStatus(startTimestamp, attempts);
            if (shouldStop) {
                stopPolling();
            }
        }, POLL_INTERVAL_MS);
    }, [checkStatus, stopPolling]);

    const generatePowerPoint = async () => {
        if (!topic.trim()) {
            toast.error('Please enter a research topic!');
            return;
        }

        try {
            setLoading(true);
            setResult(null);
            setGeneratedFiles([]);
            setPollCount(0);

            // Show progress updates
            setLoadingStatus('🔍 Researching topic on the web...');
            const statusUpdates = [
                { delay: 5000, status: '📚 Gathering research materials...' },
                { delay: 15000, status: '✍️ Preparing presentation content...' },
                { delay: 30000, status: '🎨 Generating PowerPoint with SlideSpeak...' },
                { delay: 60000, status: '⏳ Still working... (presentations take 1-2 minutes)' },
                { delay: 90000, status: '📥 Finalizing presentation...' },
                { delay: 120000, status: '🔄 Almost there...' },
            ];

            statusTimeoutsRef.current = statusUpdates.map(({ delay, status }) =>
                setTimeout(() => setLoadingStatus(status), delay)
            );

            const response = await axios.post<GenerationResult & { start_timestamp: number }>(
                `${import.meta.env.VITE_API_URL}/generate-ppt`,
                { topic },
                {
                    headers: { 'Content-Type': 'application/json' },
                    timeout: 30000 // 30 second timeout for initial request
                }
            );

            // Show initial pending result
            setResult({
                ...response.data,
                status: 'pending'
            });

            // Start polling for completion
            const startTimestamp = response.data.start_timestamp || (Date.now() / 1000);
            toast.info('🚀 Generation started! Watching for your PowerPoint...');
            startPolling(startTimestamp);

        } catch (error: any) {
            console.error(error);
            stopPolling();
            setLoading(false);
            setLoadingStatus('');
            const errorMsg = error.response?.data?.error || 'Failed to generate PowerPoint. Please try again.';
            toast.error(errorMsg);
            setResult({
                message: errorMsg,
                output_directory: OUTPUT_DIRECTORY,
                status: 'error'
            });
        }
    };

    return (
        <Card className="max-w-2xl mx-auto mt-8 border-t-4 border-purple-500 shadow-2xl bg-gradient-to-br from-white to-purple-50">
            <div className="flex items-center mb-4">
                <div className="w-12 h-12 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-xl flex items-center justify-center mr-4 shadow-lg">
                    <span className="text-2xl">🦜</span>
                </div>
                <div>
                    <h2 className="text-2xl font-bold text-gray-800">
                        PowerPoint Generator
                    </h2>
                    <p className="text-sm text-purple-600 font-medium">Powered by SlideSpeak + OpenClaw</p>
                </div>
            </div>

            <p className="text-gray-600 mb-6">
                Enter a research topic below. OpenClaw will research it on the web and generate a professional PowerPoint presentation using SlideSpeak.
            </p>

            <div className="space-y-4">
                <div className="relative">
                    <textarea
                        className="w-full p-4 bg-white border-2 border-purple-100 rounded-xl focus:ring-2 focus:ring-purple-500 focus:border-purple-300 outline-none transition-all text-gray-900 placeholder:text-gray-400 resize-none shadow-inner"
                        rows={4}
                        placeholder="e.g., The future of sustainable energy technologies and their economic impact..."
                        value={topic}
                        onChange={(e) => setTopic(e.target.value)}
                        disabled={loading}
                    />
                    <div className="absolute bottom-3 right-3 text-xs text-gray-400">
                        {topic.length} characters
                    </div>
                </div>

                <div className="bg-purple-50 border border-purple-100 rounded-lg p-3 text-sm">
                    <div className="flex items-center justify-between">
                        <div className="flex items-start">
                            <span className="text-purple-500 mr-2">📁</span>
                            <div>
                                <span className="text-gray-600">Output Directory: </span>
                                <code className="text-purple-700 bg-purple-100 px-2 py-0.5 rounded text-xs font-mono">
                                    {OUTPUT_DIRECTORY}
                                </code>
                            </div>
                        </div>
                        <button
                            onClick={async () => {
                                try {
                                    await axios.post(`${import.meta.env.VITE_API_URL}/open-output-dir`);
                                    toast.success('📂 Opened folder in Finder');
                                } catch (error) {
                                    toast.error('Failed to open folder');
                                }
                            }}
                            className="ml-3 px-3 py-1.5 bg-purple-600 text-white text-xs font-medium rounded-lg hover:bg-purple-700 transition-colors flex items-center shadow-sm"
                        >
                            <span className="mr-1">📂</span>
                            Open in Finder
                        </button>
                    </div>
                </div>

                <button
                    className={`w-full px-6 py-4 rounded-xl text-white font-semibold text-lg shadow-lg transition-all transform ${loading
                        ? 'bg-gray-400 cursor-not-allowed'
                        : 'bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-700 hover:to-indigo-700 hover:shadow-xl hover:-translate-y-0.5 active:scale-[0.98]'
                        }`}
                    onClick={generatePowerPoint}
                    disabled={loading}
                >
                    {loading ? (
                        <div className="flex items-center justify-center">
                            <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                            <span className="flex-1">{loadingStatus || 'Processing...'}</span>
                            {pollCount > 0 && (
                                <span className="ml-2 text-sm opacity-75">
                                    ({Math.floor(pollCount * 5)}s)
                                </span>
                            )}
                        </div>
                    ) : (
                        <span className="flex items-center justify-center">
                            <span className="mr-2">📊</span>
                            Generate PowerPoint Presentation
                        </span>
                    )}
                </button>
            </div>

            {result && (
                <div className={`mt-8 p-6 rounded-xl border-2 transition-all transform animate-fadeIn ${result.status === 'completed'
                    ? 'bg-green-50 border-green-200'
                    : result.status === 'pending'
                        ? 'bg-yellow-50 border-yellow-200'
                        : 'bg-red-50 border-red-200'
                    }`}>
                    <div className="flex items-start">
                        <span className="text-3xl mr-4">
                            {result.status === 'completed' ? '✅' : result.status === 'pending' ? '⏳' : '❌'}
                        </span>
                        <div className="flex-1">
                            <h3 className={`text-lg font-bold mb-2 ${result.status === 'completed'
                                ? 'text-green-800'
                                : result.status === 'pending'
                                    ? 'text-yellow-800'
                                    : 'text-red-800'
                                }`}>
                                {result.status === 'completed'
                                    ? 'PowerPoint Generated!'
                                    : result.status === 'pending'
                                        ? 'Generation In Progress...'
                                        : 'Generation Failed'}
                            </h3>
                            <p className={`mb-4 ${result.status === 'completed'
                                ? 'text-green-700'
                                : result.status === 'pending'
                                    ? 'text-yellow-700'
                                    : 'text-red-700'
                                }`}>
                                {result.message}
                            </p>

                            {/* Show generated files */}
                            {generatedFiles.length > 0 && (
                                <div className="space-y-2 mb-4">
                                    {generatedFiles.map((file, index) => (
                                        <div key={index} className="bg-white rounded-lg p-4 border border-green-200 shadow-sm">
                                            <div className="flex items-center">
                                                <span className="text-3xl mr-3">📊</span>
                                                <div className="flex-1">
                                                    <p className="font-semibold text-gray-900">{file.name}</p>
                                                    <p className="text-sm text-gray-500">{file.size_formatted}</p>
                                                </div>
                                                <div className="text-green-500">
                                                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                                    </svg>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <div className="bg-white rounded-lg p-4 border shadow-sm">
                                <div className="flex items-center mb-2">
                                    <span className="text-xl mr-2">📁</span>
                                    <span className="text-sm text-gray-500">Output Directory:</span>
                                </div>
                                <code className="block p-3 bg-gray-100 rounded-lg text-purple-700 font-mono text-sm break-all">
                                    {result.output_directory}
                                </code>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Generated Presentations List */}
            <div className="mt-8 border-t border-purple-100 pt-6">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-bold text-gray-800 flex items-center">
                        <span className="mr-2">📊</span>
                        Generated Presentations
                    </h3>
                    <button
                        onClick={fetchExistingFiles}
                        disabled={loadingFiles}
                        className="text-purple-600 hover:text-purple-800 text-sm font-medium flex items-center transition-colors"
                    >
                        {loadingFiles ? (
                            <svg className="animate-spin h-4 w-4 mr-1" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                        ) : (
                            <span className="mr-1">🔄</span>
                        )}
                        Refresh
                    </button>
                </div>

                {loadingFiles && allFiles.length === 0 ? (
                    <div className="text-center py-8 text-gray-500">
                        <svg className="animate-spin h-8 w-8 mx-auto mb-2 text-purple-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        Loading presentations...
                    </div>
                ) : allFiles.length === 0 ? (
                    <div className="text-center py-8 text-gray-500 bg-gray-50 rounded-lg">
                        <span className="text-4xl mb-2 block">📭</span>
                        <p>No presentations yet.</p>
                        <p className="text-sm mt-1">Generate your first PowerPoint above!</p>
                    </div>
                ) : (
                    <div className="space-y-2 max-h-80 overflow-y-auto">
                        {allFiles.map((file) => {
                            const isNew = generatedFiles.some(gf => gf.name === file.name);
                            const date = new Date(file.created_at * 1000);
                            const timeAgo = getTimeAgo(date);

                            return (
                                <div
                                    key={file.name}
                                    className={`bg-white rounded-lg p-4 border shadow-sm transition-all hover:shadow-md ${isNew ? 'border-green-300 bg-green-50' : 'border-gray-200'
                                        }`}
                                >
                                    <div className="flex items-center">
                                        <span className="text-2xl mr-3">📊</span>
                                        <div className="flex-1 min-w-0">
                                            <p className="font-semibold text-gray-900 truncate" title={file.name}>
                                                {file.name}
                                            </p>
                                            <p className="text-sm text-gray-500">
                                                {file.size_formatted} • {timeAgo}
                                            </p>
                                        </div>
                                        {isNew && (
                                            <span className="ml-2 px-2 py-1 bg-green-100 text-green-700 text-xs font-medium rounded-full">
                                                New
                                            </span>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            <style>{`
                @keyframes fadeIn {
                    from { opacity: 0; transform: translateY(10px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                .animate-fadeIn {
                    animation: fadeIn 0.3s ease-out forwards;
                }
            `}</style>
        </Card>
    );
};

export default PowerPointGenerator;
