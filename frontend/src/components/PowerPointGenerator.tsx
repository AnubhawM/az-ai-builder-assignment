import React, { useState } from 'react';
import axios from 'axios';
import { toast } from 'react-toastify';
import Card from './ui/Card';

interface GenerationResult {
    message: string;
    output_directory: string;
    file_name?: string;
    status: 'pending' | 'completed' | 'error';
}

const PowerPointGenerator: React.FC = () => {
    const [topic, setTopic] = useState<string>('');
    const [loading, setLoading] = useState<boolean>(false);
    const [loadingStatus, setLoadingStatus] = useState<string>('');
    const [result, setResult] = useState<GenerationResult | null>(null);

    const OUTPUT_DIRECTORY = '/Users/anubhawmathur/development/ppt-output';

    const generatePowerPoint = async () => {
        if (!topic.trim()) {
            toast.error('Please enter a research topic!');
            return;
        }

        try {
            setLoading(true);
            setResult(null);

            // Show progress updates
            setLoadingStatus('🔍 Researching topic on the web...');
            const statusUpdates = [
                { delay: 5000, status: '📚 Gathering research materials...' },
                { delay: 15000, status: '✍️ Preparing presentation content...' },
                { delay: 30000, status: '🎨 Generating PowerPoint with SlideSpeak...' },
                { delay: 60000, status: '⏳ Still working... (presentations take 30-60 seconds)' },
                { delay: 90000, status: '📥 Almost done, finalizing...' },
            ];

            const timeouts = statusUpdates.map(({ delay, status }) =>
                setTimeout(() => setLoadingStatus(status), delay)
            );

            const response = await axios.post<GenerationResult>(
                `${import.meta.env.VITE_API_URL}/generate-ppt`,
                { topic },
                {
                    headers: { 'Content-Type': 'application/json' },
                    timeout: 300000 // 5 minute timeout
                }
            );

            // Clear all status timeouts
            timeouts.forEach(t => clearTimeout(t));

            setResult(response.data);

            if (response.data.status === 'completed') {
                toast.success('🎉 PowerPoint generated successfully!');
            } else if (response.data.status === 'pending') {
                toast.info('PowerPoint generation started. Check the output directory soon.');
            }
        } catch (error: any) {
            console.error(error);
            const errorMsg = error.response?.data?.error || 'Failed to generate PowerPoint. Please try again.';
            toast.error(errorMsg);
        } finally {
            setLoading(false);
            setLoadingStatus('');
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
                    <div className="flex items-start">
                        <span className="text-purple-500 mr-2">📁</span>
                        <div>
                            <span className="text-gray-600">Output Directory: </span>
                            <code className="text-purple-700 bg-purple-100 px-2 py-0.5 rounded text-xs font-mono">
                                {OUTPUT_DIRECTORY}
                            </code>
                        </div>
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
                            {loadingStatus || 'Processing...'}
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
                                        ? 'Generation In Progress'
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

                            <div className="bg-white rounded-lg p-4 border shadow-sm">
                                <div className="flex items-center mb-2">
                                    <span className="text-2xl mr-3">📊</span>
                                    <div>
                                        {result.file_name && (
                                            <p className="font-semibold text-gray-900">{result.file_name}</p>
                                        )}
                                        <p className="text-sm text-gray-500">Saved to:</p>
                                    </div>
                                </div>
                                <code className="block mt-2 p-3 bg-gray-100 rounded-lg text-purple-700 font-mono text-sm break-all">
                                    {result.output_directory}
                                </code>
                            </div>
                        </div>
                    </div>
                </div>
            )}

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
