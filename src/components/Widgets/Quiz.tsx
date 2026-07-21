import { useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

const Quiz = ({ initialState }) => {
    const { t } = useTranslation();
    const cards = initialState?.cards || [];
    const [currentIndex, setCurrentIndex] = useState(0);
    const [score, setScore] = useState(0);
    const [showResult, setShowResult] = useState(false);
    const [selectedChoice, setSelectedChoice] = useState(null);
    const [showHint, setShowHint] = useState(false);
    const [focusedChoice, setFocusedChoice] = useState(0);
    const choiceRefs = useRef([]);
    const questionId = useId();
    const hintId = useId();

    const currentCard = cards[currentIndex];

    const handleChoice = (choiceIndex) => {
        if (selectedChoice !== null) return;

        const correct = choiceIndex === currentCard.correct_index;
        setSelectedChoice(choiceIndex);
        if (correct) setScore(s => s + 1);
    };

    const focusChoice = (choiceIndex) => {
        setFocusedChoice(choiceIndex);
        window.requestAnimationFrame(() => choiceRefs.current[choiceIndex]?.focus());
    };

    const handleChoiceKeyDown = (event, choiceIndex) => {
        const choiceCount = currentCard?.choices?.length || 0;
        if (choiceCount === 0) return;

        let nextChoice = choiceIndex;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
            nextChoice = (choiceIndex + 1) % choiceCount;
        } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
            nextChoice = (choiceIndex - 1 + choiceCount) % choiceCount;
        } else if (event.key === 'Home') {
            nextChoice = 0;
        } else if (event.key === 'End') {
            nextChoice = choiceCount - 1;
        } else {
            return;
        }

        event.preventDefault();
        focusChoice(nextChoice);
    };

    const nextQuestion = () => {
        if (currentIndex < cards.length - 1) {
            setCurrentIndex(prev => prev + 1);
            setSelectedChoice(null);
            setShowHint(false);
            focusChoice(0);
        } else {
            setShowResult(true);
        }
    };

    const restart = () => {
        setCurrentIndex(0);
        setScore(0);
        setShowResult(false);
        setSelectedChoice(null);
        setShowHint(false);
        focusChoice(0);
    };

    if (!currentCard && !showResult) return <div>{t('quiz.dataError')}</div>;

    return (
        <div className="quiz-container">
            {showResult ? (
                <div className="quiz-card results-card">
                    <h2>{t('quiz.completed')}</h2>
                    <p>{t('quiz.score', { score, total: cards.length })}</p>
                    <button type="button" className="next-button" onClick={restart}>{t('quiz.tryAgain')}</button>
                </div>
            ) : (
                <div className="quiz-card">
                    <div className="quiz-header">
                        <span>{t('quiz.question', { current: currentIndex + 1, total: cards.length })}</span>
                        <div
                            className="progress-bar-container"
                            role="progressbar"
                            aria-label={t('quiz.question', { current: currentIndex + 1, total: cards.length })}
                            aria-valuemin={1}
                            aria-valuemax={cards.length}
                            aria-valuenow={currentIndex + 1}
                        >
                            <div className="progress-bar-fill" style={{ width: `${((currentIndex + 1) / cards.length) * 100}%` }}></div>
                        </div>
                    </div>
                    <div className="quiz-body">
                        <h2 id={questionId}>{currentCard.question}</h2>
                        <ul className="choices-grid" role="radiogroup" aria-labelledby={questionId}>
                            {currentCard.choices.map((choice, idx) => {
                                let className = 'choice-item';
                                const isCorrectChoice = idx === currentCard.correct_index;
                                const isSelectedChoice = idx === selectedChoice;
                                if (selectedChoice !== null) {
                                    className += ' disabled';
                                    if (isCorrectChoice) className += ' correct';
                                    else if (isSelectedChoice) className += ' incorrect';
                                }
                                const statusLabel = selectedChoice === null
                                    ? null
                                    : isCorrectChoice
                                        ? t('quiz.correctAnswer')
                                        : isSelectedChoice
                                            ? t('quiz.incorrectAnswer')
                                            : null;
                                return (
                                    <li key={idx} className="choice-list-item">
                                        <button
                                            ref={(element) => { choiceRefs.current[idx] = element; }}
                                            type="button"
                                            role="radio"
                                            aria-checked={isSelectedChoice}
                                            aria-disabled={selectedChoice !== null}
                                            className={className}
                                            tabIndex={focusedChoice === idx ? 0 : -1}
                                            onFocus={() => setFocusedChoice(idx)}
                                            onKeyDown={(event) => handleChoiceKeyDown(event, idx)}
                                            onClick={() => handleChoice(idx)}
                                        >
                                            <span>{choice}</span>
                                            {statusLabel && <span className="sr-only">{statusLabel}</span>}
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                        <p className="sr-only" role="status" aria-live="polite">
                            {selectedChoice === null
                                ? ''
                                : selectedChoice === currentCard.correct_index
                                    ? t('quiz.correctAnswer')
                                    : t('quiz.incorrectAnswer')}
                        </p>
                    </div>
                    <div className="quiz-footer">
                        <div className="hint-section">
                            <button
                                type="button"
                                className="hint-button"
                                aria-expanded={showHint}
                                aria-controls={hintId}
                                onClick={() => setShowHint(!showHint)}
                            >
                                {t('quiz.hint')}
                            </button>
                            <p id={hintId} aria-hidden={!showHint} className={`hint-text ${showHint ? 'visible' : ''}`}>{currentCard.hint}</p>
                        </div>
                        {selectedChoice !== null && (
                            <button type="button" className="next-button" style={{display: 'block'}} onClick={nextQuestion}>{t('quiz.next')}</button>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default Quiz;
