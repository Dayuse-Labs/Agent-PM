/**
 * Image Carousel
 * Hotel image gallery with swipe support
 */

import { scrollBehavior } from '../motion.js';
import { state, carousels } from '../state.js';

/**
 * Select best image based on query context
 */
export function selectBestImage(images, query, hotelData) {
    if (!images || images.length <= 1) return images;

    const photosWithTags = hotelData.photos_with_tags || [];
    const queryLower = (query || state.currentUserQuery || '').toLowerCase();

    // Keyword to AI tag mapping with priority weights
    const keywordPriority = [
        { keywords: ['pool', 'piscine', 'swim', 'swimming'], tags: ['pool', 'outdoor_pool', 'indoor_pool'], weight: 50 },
        { keywords: ['view', 'rooftop', 'terrace', 'skyline'], tags: ['view', 'city_view', 'ocean_view', 'rooftop', 'balcony', 'terrace'], weight: 15 },
        { keywords: ['spa', 'wellness', 'massage'], tags: ['spa', 'gym', 'fitness'], weight: 12 },
        { keywords: ['gym', 'fitness', 'sport', 'workout'], tags: ['gym', 'fitness'], weight: 12 },
        { keywords: ['romantic', 'couple', 'honeymoon', 'anniversary'], tags: ['bed', 'bedroom', 'suite', 'view'], weight: 8 },
        { keywords: ['restaurant', 'dining', 'food', 'bar', 'breakfast'], tags: ['restaurant', 'dining', 'bar'], weight: 10 },
        { keywords: ['relax', 'chill', 'rest', 'quiet'], tags: ['room', 'bedroom', 'suite', 'pool', 'garden', 'view'], weight: 8 },
        { keywords: ['room', 'bed', 'sleep', 'bedroom'], tags: ['room', 'bedroom', 'bed', 'suite'], weight: 7 }
    ];

    // Find relevant tags with weights
    let targetTags = [];
    for (const priority of keywordPriority) {
        if (priority.keywords.some(k => queryLower.includes(k))) {
            targetTags.push(...priority.tags.map(tag => ({ tag, weight: priority.weight })));
        }
    }

    // Default fallback: prioritize room photos when no specific keyword
    if (targetTags.length === 0) {
        targetTags = [
            { tag: 'room', weight: 10 }, { tag: 'bedroom', weight: 10 },
            { tag: 'bed', weight: 10 }, { tag: 'suite', weight: 10 },
            { tag: 'facade', weight: 5 }
        ];
    }

    if (photosWithTags.length === 0) {
        return images;
    }

    // Find best image to put first
    let bestIndex = 0;
    let bestScore = 0;

    images.forEach((url, index) => {
        const photoData = photosWithTags[index];
        if (!photoData || !photoData.success || !photoData.tags || !Array.isArray(photoData.tags)) {
            return;
        }

        const photoTags = photoData.tags;
        const score = targetTags.reduce((acc, { tag, weight }) => {
            return acc + (photoTags.includes(tag) ? weight : 0);
        }, 0);

        if (score > bestScore) {
            bestScore = score;
            bestIndex = index;
        }
    });

    if (bestIndex === 0 || bestScore === 0) {
        return images;
    }

    // Build reordered array: best image first, then rest in original order
    const reorderedImages = [images[bestIndex]];
    for (let i = 0; i < images.length; i++) {
        if (i !== bestIndex) {
            reorderedImages.push(images[i]);
        }
    }

    console.log(`Image reorder for "${queryLower}": moved photo #${bestIndex} (score: ${bestScore}) to first position`);

    return reorderedImages;
}

/**
 * Update image carousel position
 */
export function updateImageCarousel(hotelId) {
    const carousel = carousels.get(hotelId);
    if (!carousel) return;

    const wrapper = document.querySelector(`#carousel-${hotelId} .image-carousel-wrapper`);
    if (!wrapper) return;

    const width = wrapper.clientWidth;
    wrapper.scrollTo({
        left: carousel.currentImage * width,
        behavior: scrollBehavior()
    });

    updateCarouselDots(hotelId, carousel.currentImage);
}

/**
 * Handle manual scroll on image carousel
 */
export function handleImageScroll(event, hotelId) {
    const wrapper = event.target;
    const width = wrapper.clientWidth;
    const index = Math.round(wrapper.scrollLeft / width);

    const carousel = carousels.get(hotelId);
    if (!carousel || carousel.currentImage === index) return;

    carousel.currentImage = index;
    updateCarouselDots(hotelId, index);
}

/**
 * Update carousel dot indicators
 */
function updateCarouselDots(hotelId, index) {
    document.querySelectorAll(`.carousel-dot[data-carousel="${hotelId}"]`).forEach((dot, i) => {
        dot.classList.toggle('active', i === index);
    });
}

/**
 * Navigate to next image
 */
export function nextImage(hotelId) {
    const carousel = carousels.get(hotelId);
    if (!carousel) return;

    if (carousel.currentImage < carousel.totalImages - 1) {
        carousel.currentImage++;
        updateImageCarousel(hotelId);
    }
}

/**
 * Navigate to previous image
 */
export function prevImage(hotelId) {
    const carousel = carousels.get(hotelId);
    if (!carousel) return;

    if (carousel.currentImage > 0) {
        carousel.currentImage--;
        updateImageCarousel(hotelId);
    }
}

/**
 * Go to specific image
 */
export function goToImage(hotelId, index) {
    const carousel = carousels.get(hotelId);
    if (!carousel) return;

    carousel.currentImage = index;
    updateImageCarousel(hotelId);
}
